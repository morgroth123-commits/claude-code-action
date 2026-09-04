from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .policy import PermissionPolicy
from .sandbox import SandboxRunner


_PROTECTED_PATH_COMPONENTS = frozenset(
    {
        ".aws",
        ".azure",
        ".chatmpd",
        ".git",
        ".secrets",
        ".ssh",
        "secret",
        "secrets",
    }
)


@dataclass(frozen=True)
class CheckResult:
    argv: list[str]
    exit_code: int
    sequence: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class RunResult:
    status: str
    summary: str
    changed_files: list[str]
    checks: list[CheckResult]
    state_file: Path


class AgentEngine:
    def __init__(
        self,
        workspace: Path,
        model: Any,
        policy: PermissionPolicy,
        *,
        command_runner: Any | None = None,
    ) -> None:
        self.workspace = workspace.resolve(strict=True)
        self.model = model
        self.policy = policy
        self.command_runner = command_runner or SandboxRunner()
        self.events: list[dict[str, Any]] = []
        self.changed_files: list[str] = []
        self.checks: list[CheckResult] = []
        self.last_write_sequence = 0
        self.last_exit_code: int | None = None
        self.last_tool_error: dict[str, str] | None = None

    def run(self, task: str) -> RunResult:
        self._reset_run_state()
        run_id = uuid.uuid4().hex
        run_directory = self._prepare_run_directory(run_id)
        state_file = run_directory / "run.json"
        events_file = run_directory / "events.jsonl"
        self._record(events_file, "run_created", {"task": task})
        plan_accepted = False
        try:
            for _ in range(50):
                context = {
                    "task": task,
                    "last_exit_code": self.last_exit_code,
                    "last_tool_error": self.last_tool_error,
                    "changed_files": list(self.changed_files),
                    "events": list(self.events),
                }
                turn = self.model.next_turn(context)
                self._record(events_file, "model_turn", {"kind": turn.get("kind")})
                kind = turn.get("kind")
                if not plan_accepted:
                    if kind != "plan":
                        raise RuntimeError("The model must begin with a plan")
                    plan_accepted = True
                    self._record(events_file, "plan_accepted", {"steps": turn["steps"]})
                    continue
                if kind == "tool":
                    try:
                        self._execute_tool(turn, events_file)
                    except PermissionError:
                        raise
                    except Exception as error:
                        self.last_tool_error = {
                            "tool": str(turn.get("name", "")),
                            "error_type": type(error).__name__,
                            "message": str(error)[:2_000],
                        }
                        self._record(events_file, "tool_failed", self.last_tool_error)
                    continue
                if kind == "final":
                    if (
                        turn.get("outcome") == "success"
                        and not self._verification_is_fresh()
                    ):
                        self._record(
                            events_file,
                            "completion_rejected",
                            {
                                "reason": (
                                    "Required checks have not passed after the last write"
                                )
                            },
                        )
                        continue
                    status = (
                        "succeeded" if turn.get("outcome") == "success" else "failed"
                    )
                    summary = str(turn.get("summary", ""))
                    self._record(events_file, f"run_{status}", {"summary": summary})
                    self._save_state(state_file, run_id, task, status, summary)
                    return RunResult(
                        status,
                        summary,
                        list(self.changed_files),
                        list(self.checks),
                        state_file,
                    )
                raise RuntimeError(f"Unsupported model turn: {kind!r}")
            raise RuntimeError("The model exceeded ChatMPD's turn limit")
        except Exception as error:
            summary = (
                f"{type(self.model).__name__}: {type(error).__name__}: {error}"
            )
            self._record(events_file, "run_failed", {"summary": summary})
            self._save_state(state_file, run_id, task, "failed", summary)
            raise

    def _reset_run_state(self) -> None:
        self.events = []
        self.changed_files = []
        self.checks = []
        self.last_write_sequence = 0
        self.last_exit_code = None
        self.last_tool_error = None

    def _execute_tool(self, turn: dict[str, Any], events_file: Path) -> None:
        name = str(turn.get("name"))
        arguments = turn.get("arguments", {})
        self._record(events_file, "tool_requested", {"name": name})
        if name == "list_files":
            requested = str(arguments.get("path", "."))
            if requested in {"", "."}:
                path = self.workspace
                relative = "."
            else:
                path, relative = self._safe_path(requested)
            if not path.is_dir():
                raise NotADirectoryError(f"Not a project directory: {relative}")
            self._record(events_file, "permission_allowed", {"tool": name})
            self._record(events_file, "tool_started", {"tool": name})
            result = self._list_files(path, relative)
        elif name == "read_file":
            path, relative = self._safe_path(str(arguments["path"]))
            self._record(events_file, "permission_allowed", {"tool": name})
            self._record(events_file, "tool_started", {"tool": name})
            if path.stat().st_size > 262_144:
                raise RuntimeError("File exceeds the 256 KiB read limit")
            with path.open("r", encoding="utf-8", newline="") as source:
                content = source.read()
            if len(content.encode("utf-8")) > 262_144:
                raise RuntimeError("File exceeds the 256 KiB read limit")
            result = {
                "path": relative,
                "content": content,
                "bytes": len(content.encode("utf-8")),
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
        elif name == "search_text":
            query = str(arguments.get("query", ""))
            if not query or len(query.encode("utf-8")) > 4_096:
                raise ValueError("Search query must contain 1 to 4096 UTF-8 bytes")
            requested = str(arguments.get("path", "."))
            case_sensitive = bool(arguments.get("case_sensitive", False))
            self._record(events_file, "permission_allowed", {"tool": name})
            self._record(events_file, "tool_started", {"tool": name})
            result = self._search_text(requested, query, case_sensitive)
        elif name == "replace_text":
            path, relative = self._safe_path(str(arguments["path"]))
            if not self.policy.permits_write(relative):
                raise PermissionError(f"Writing {relative!r} is not permitted")
            old_text = str(arguments.get("old_text", ""))
            new_text = str(arguments.get("new_text", ""))
            expected = int(arguments.get("expected_replacements", 1))
            if not old_text:
                raise ValueError("old_text must not be empty")
            if expected < 1 or expected > 1_000:
                raise ValueError("expected_replacements must be between 1 and 1000")
            self._record(events_file, "permission_allowed", {"tool": name})
            self._record(events_file, "tool_started", {"tool": name})
            result = self._replace_text(
                path, relative, old_text, new_text, expected, events_file.parent
            )
            if relative not in self.changed_files:
                self.changed_files.append(relative)
        elif name == "write_file":
            path, relative = self._safe_path(str(arguments["path"]))
            if not self.policy.permits_write(relative):
                raise PermissionError(f"Writing {relative!r} is not permitted")
            content = str(arguments["content"])
            encoded_content = content.encode("utf-8")
            if len(encoded_content) > 262_144:
                raise RuntimeError("File exceeds the 256 KiB write limit")
            self._record(events_file, "permission_allowed", {"tool": name})
            self._record(events_file, "tool_started", {"tool": name})
            self._backup_original(path, relative, events_file.parent)
            path.parent.mkdir(parents=True, exist_ok=True)
            previous_stat = path.stat() if path.exists() else None
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="",
                dir=path.parent,
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary_path = Path(temporary.name)
            try:
                revalidated, canonical = self._safe_path(relative)
                if revalidated != path or canonical != relative:
                    raise PermissionError("The write target changed during validation")
                os.replace(temporary_path, path)
            finally:
                temporary_path.unlink(missing_ok=True)
            self._ensure_changed_timestamp(path, previous_stat, len(encoded_content))
            if relative not in self.changed_files:
                self.changed_files.append(relative)
            result = {"path": relative, "bytes": len(encoded_content)}
        elif name == "run_command":
            argv = [str(value) for value in arguments["argv"]]
            if not self.policy.permits_command(argv):
                raise PermissionError("The requested command is not permitted")
            self._record(events_file, "permission_allowed", {"tool": name})
            self._record(events_file, "tool_started", {"tool": name})
            completed = self.command_runner.run(
                self.workspace,
                argv,
                timeout_seconds=60,
                output_limit_bytes=65_536,
            )
            if completed.exit_code is None or completed.status not in {
                "completed",
                "timed_out",
            }:
                raise RuntimeError(
                    completed.error or "The isolated command runner was unavailable"
                )
            exit_code = completed.exit_code
            stderr = completed.stderr
            if completed.error:
                stderr = f"{stderr}\n{completed.error}".strip()
            combined_output = f"{completed.stdout}\n{stderr}"
            if (
                exit_code == 0
                and len(argv) >= 4
                and argv[1:4] == ["-m", "unittest", "discover"]
                and re.search(r"\bRan\s+0\s+tests?\b", combined_output)
            ):
                exit_code = 5
                stderr = (
                    f"{stderr}\nNo tests were discovered; verification is incomplete."
                ).strip()
            self.last_exit_code = exit_code
            result = {
                "argv": argv,
                "exit_code": exit_code,
                "stdout": completed.stdout,
                "stderr": stderr,
                "sandbox_status": completed.status,
            }
        else:
            raise RuntimeError(f"Unknown tool: {name}")

        self._record(
            events_file,
            "tool_finished",
            {"tool": name, "result": result},
            persisted_data={
                "tool": name,
                "result": self._persistent_tool_result(name, result),
            },
        )
        self.last_tool_error = None
        sequence = len(self.events)
        if name in {"write_file", "replace_text"}:
            self.last_write_sequence = sequence
        if name == "run_command":
            if self.policy.is_required_check(result["argv"]):
                self.checks.append(
                    CheckResult(
                        result["argv"],
                        result["exit_code"],
                        sequence,
                        result["stdout"],
                        result["stderr"],
                    )
                )
            else:
                self.last_write_sequence = sequence

    def _safe_path(self, requested: str) -> tuple[Path, str]:
        candidate = Path(requested)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise PermissionError("Only contained workspace-relative paths are allowed")
        normalized = Path(*[part for part in candidate.parts if part not in ("", ".")])
        for part in normalized.parts:
            self._validate_path_component(part)
        lowered_parts = [part.lower() for part in normalized.parts]
        if not normalized.parts or _PROTECTED_PATH_COMPONENTS.intersection(
            lowered_parts
        ):
            raise PermissionError("That path is protected")
        if self._is_sensitive_path(normalized):
            raise PermissionError("That path is sensitive and cannot be read or changed")
        current = self.workspace
        for part in normalized.parts:
            current /= part
            is_junction = getattr(os.path, "isjunction", lambda unused: False)
            if current.is_symlink() or is_junction(current):
                raise PermissionError("Symbolic links and junctions are protected")
        resolved = (self.workspace / normalized).resolve(strict=False)
        if resolved != self.workspace and self.workspace not in resolved.parents:
            raise PermissionError("The path escapes the workspace")
        canonical_relative = resolved.relative_to(self.workspace)
        canonical_parts = [part.lower() for part in canonical_relative.parts]
        if _PROTECTED_PATH_COMPONENTS.intersection(canonical_parts):
            raise PermissionError("That path resolves into protected state")
        if self._is_sensitive_path(canonical_relative):
            raise PermissionError("That path resolves to a sensitive file")
        return resolved, canonical_relative.as_posix()

    def _prepare_run_directory(self, run_id: str) -> Path:
        state_root = self.workspace / ".chatmpd"
        runs_root = state_root / "runs"
        for directory in (state_root, runs_root):
            is_junction = getattr(os.path, "isjunction", lambda unused: False)
            if directory.is_symlink() or is_junction(directory):
                raise PermissionError(
                    "ChatMPD run state must not use symbolic links or junctions"
                )
            if directory.exists() and not directory.is_dir():
                raise PermissionError(
                    "ChatMPD run state must use ordinary directories"
                )
            directory.mkdir(exist_ok=True)
            if directory.is_symlink() or is_junction(directory):
                raise PermissionError(
                    "ChatMPD run state changed into a protected link"
                )
            resolved = directory.resolve(strict=True)
            if resolved != self.workspace and self.workspace not in resolved.parents:
                raise PermissionError(
                    "ChatMPD run state must remain inside the workspace"
                )
        run_directory = runs_root / run_id
        run_directory.mkdir(exist_ok=False)
        return run_directory

    def _list_files(self, root: Path, relative_root: str) -> dict[str, Any]:
        excluded_directories = {
            *_PROTECTED_PATH_COMPONENTS,
            ".venv",
            "__pycache__",
            "build",
            "dist",
            "node_modules",
            "venv",
        }
        files: list[dict[str, Any]] = []
        pending: list[tuple[Path, int]] = [(root, 0)]
        truncated = False
        is_junction = getattr(os.path, "isjunction", lambda unused: False)
        while pending and not truncated:
            directory, depth = pending.pop()
            try:
                entries = sorted(os.scandir(directory), key=lambda item: item.name)
            except OSError as error:
                raise RuntimeError(f"Could not list {directory.name}: {error}") from error
            for entry in entries:
                if entry.is_symlink() or is_junction(entry.path):
                    continue
                entry_path = Path(entry.path)
                relative = entry_path.relative_to(self.workspace)
                try:
                    for part in relative.parts:
                        self._validate_path_component(part)
                except PermissionError:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.casefold() in excluded_directories or depth >= 8:
                        continue
                    pending.append((entry_path, depth + 1))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if self._is_sensitive_path(relative):
                    continue
                try:
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
                files.append({"path": relative.as_posix(), "bytes": size})
                if len(files) >= 1_000:
                    truncated = True
                    break
        files.sort(key=lambda item: item["path"].casefold())
        return {"root": relative_root, "files": files, "truncated": truncated}

    def _search_text(
        self, requested: str, query: str, case_sensitive: bool
    ) -> dict[str, Any]:
        if requested in {"", "."}:
            root, relative_root = self.workspace, "."
        else:
            root, relative_root = self._safe_path(requested)
        if not root.exists():
            raise FileNotFoundError(f"Search path does not exist: {relative_root}")
        if root.is_file():
            candidates = [{"path": relative_root, "bytes": root.stat().st_size}]
            inventory_truncated = False
        elif root.is_dir():
            inventory = self._list_files(root, relative_root)
            candidates = list(inventory["files"])
            inventory_truncated = bool(inventory["truncated"])
        else:
            raise RuntimeError(f"Search path is not a regular file or directory: {relative_root}")

        needle = query if case_sensitive else query.casefold()
        matches: list[dict[str, Any]] = []
        truncated = inventory_truncated
        for item in candidates:
            if int(item["bytes"]) > 262_144:
                continue
            path, relative = self._safe_path(str(item["path"]))
            try:
                with path.open("r", encoding="utf-8", newline="") as source:
                    for line_number, line in enumerate(source, start=1):
                        haystack = line if case_sensitive else line.casefold()
                        if needle not in haystack:
                            continue
                        if len(matches) >= 100:
                            truncated = True
                            break
                        text = line.rstrip("\r\n")
                        matches.append(
                            {"path": relative, "line": line_number, "text": text[:500]}
                        )
            except (OSError, UnicodeDecodeError):
                continue
            if truncated and len(matches) >= 100:
                break
        return {
            "root": relative_root,
            "query": query,
            "matches": matches,
            "truncated": truncated,
        }

    def _replace_text(
        self,
        path: Path,
        relative: str,
        old_text: str,
        new_text: str,
        expected: int,
        run_directory: Path,
    ) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(f"Project file does not exist: {relative}")
        if path.stat().st_size > 262_144:
            raise RuntimeError("File exceeds the 256 KiB edit limit")
        with path.open("r", encoding="utf-8", newline="") as source:
            content = source.read()
        encoded = content.encode("utf-8")
        if len(encoded) > 262_144:
            raise RuntimeError("File exceeds the 256 KiB edit limit")
        count = content.count(old_text)
        if count != expected:
            raise ValueError(
                f"Expected {expected} replacement(s), but found {count}; file was not changed"
            )
        updated = content.replace(old_text, new_text)
        updated_bytes = updated.encode("utf-8")
        if len(updated_bytes) > 262_144:
            raise RuntimeError("Edited file would exceed the 256 KiB write limit")
        self._backup_original(path, relative, run_directory)
        previous_stat = path.stat()
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="", dir=path.parent, delete=False
        ) as temporary:
            temporary.write(updated)
            temporary_path = Path(temporary.name)
        try:
            revalidated, canonical = self._safe_path(relative)
            if revalidated != path or canonical != relative:
                raise PermissionError("The edit target changed during validation")
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
        self._ensure_changed_timestamp(path, previous_stat, len(updated_bytes))
        return {
            "path": relative,
            "replacements": count,
            "bytes": len(updated_bytes),
            "sha256": hashlib.sha256(updated_bytes).hexdigest(),
        }

    @staticmethod
    def _validate_path_component(part: str) -> None:
        if part != part.rstrip(" ."):
            raise PermissionError("Windows path aliases are protected")
        if any(character in part for character in '<>:"|?*'):
            raise PermissionError("The path contains a forbidden Windows character")
        if any(ord(character) < 32 for character in part):
            raise PermissionError("The path contains a forbidden control character")
        is_reserved = getattr(os.path, "isreserved", lambda unused: False)
        if is_reserved(part):
            raise PermissionError("Windows reserved paths are protected")
        device_name = part.split(".", 1)[0].casefold()
        reserved = {"aux", "con", "nul", "prn"}
        reserved.update(f"com{index}" for index in range(1, 10))
        reserved.update(f"lpt{index}" for index in range(1, 10))
        if device_name in reserved:
            raise PermissionError("Windows device paths are protected")

    @staticmethod
    def _is_sensitive_path(path: Path) -> bool:
        name = path.name.lower()
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            return True
        if name in {
            ".netrc",
            ".npmrc",
            ".pypirc",
            "credentials.json",
            "id_dsa",
            "id_ed25519",
            "id_ecdsa",
            "id_rsa",
            "service-account.json",
        }:
            return True
        return path.suffix.lower() in {".key", ".p12", ".pem", ".pfx"}

    def _verification_is_fresh(self) -> bool:
        if self.changed_files and not self.policy.required_checks:
            return False
        for required in self.policy.required_checks:
            matching = [
                check
                for check in self.checks
                if check.argv == required
                and check.exit_code == 0
                and check.sequence > self.last_write_sequence
            ]
            if not matching:
                return False
        return True

    @staticmethod
    def _persistent_tool_result(name: str, result: dict[str, Any]) -> dict[str, Any]:
        if name == "read_file":
            return {
                "path": result["path"],
                "bytes": result["bytes"],
                "sha256": result["sha256"],
                "content_persisted": False,
            }
        if name == "search_text":
            query = str(result.get("query", "")).encode("utf-8")
            return {
                "root": result["root"],
                "query_bytes": len(query),
                "query_sha256": hashlib.sha256(query).hexdigest(),
                "matches": [
                    {"path": match["path"], "line": match["line"]}
                    for match in result.get("matches", [])
                ],
                "truncated": bool(result.get("truncated", False)),
                "matched_text_persisted": False,
            }
        if name == "run_command":
            stdout = str(result.get("stdout", "")).encode("utf-8")
            stderr = str(result.get("stderr", "")).encode("utf-8")
            return {
                "argv": result["argv"],
                "exit_code": result["exit_code"],
                "sandbox_status": result.get("sandbox_status"),
                "stdout_bytes": len(stdout),
                "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                "stderr_bytes": len(stderr),
                "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
                "output_persisted": False,
            }
        return dict(result)

    @staticmethod
    def _ensure_changed_timestamp(
        path: Path, previous_stat: os.stat_result | None, new_size: int
    ) -> None:
        if previous_stat is None or previous_stat.st_size != new_size:
            return
        current_stat = path.stat()
        if int(current_stat.st_mtime) != int(previous_stat.st_mtime):
            return
        next_tick_ns = (int(previous_stat.st_mtime) + 1) * 1_000_000_000
        os.utime(path, ns=(current_stat.st_atime_ns, next_tick_ns))

    @staticmethod
    def _backup_original(path: Path, relative: str, run_directory: Path) -> None:
        if not path.exists():
            return
        size = path.stat().st_size
        if size > 262_144:
            raise RuntimeError("Existing file exceeds the 256 KiB backup limit")
        backup = run_directory / "backups" / Path(relative)
        if backup.exists():
            return
        backup.parent.mkdir(parents=True, exist_ok=True)
        original = path.read_bytes()
        with tempfile.NamedTemporaryFile(dir=backup.parent, delete=False) as stream:
            stream.write(original)
            temporary = Path(stream.name)
        try:
            os.replace(temporary, backup)
        finally:
            temporary.unlink(missing_ok=True)

    def _record(
        self,
        events_file: Path,
        event_type: str,
        data: dict[str, Any],
        *,
        persisted_data: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "sequence": len(self.events) + 1,
            "timestamp": datetime.now(UTC).isoformat(),
            "type": event_type,
            "data": data,
        }
        self.events.append(event)
        disk_event = (
            event
            if persisted_data is None
            else {**event, "data": persisted_data}
        )
        with events_file.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(disk_event, sort_keys=True) + "\n")

    def _save_state(
        self, state_file: Path, run_id: str, task: str, status: str, summary: str
    ) -> None:
        state = {
            "schema_version": 1,
            "run_id": run_id,
            "task": task,
            "status": status,
            "summary": summary,
            "changed_files": list(self.changed_files),
            "checks": [
                {
                    "argv": check.argv,
                    "exit_code": check.exit_code,
                    "sequence": check.sequence,
                    "stdout_bytes": len(check.stdout.encode("utf-8")),
                    "stdout_sha256": hashlib.sha256(
                        check.stdout.encode("utf-8")
                    ).hexdigest(),
                    "stderr_bytes": len(check.stderr.encode("utf-8")),
                    "stderr_sha256": hashlib.sha256(
                        check.stderr.encode("utf-8")
                    ).hexdigest(),
                    "output_persisted": False,
                }
                for check in self.checks
            ],
            "events_recorded": len(self.events),
        }
        temporary = state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(temporary, state_file)
