from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit


@dataclass(frozen=True)
class GitContext:
    is_repository: bool
    root: str | None
    branch: str | None
    dirty: bool
    origin_owner: str | None
    origin_repo: str | None
    status: str
    diff: str
    error: str | None


@dataclass(frozen=True)
class _CommandResult:
    exit_code: int
    stdout: str


def collect_git_context(
    directory: Path,
    *,
    output_limit: int = 32_768,
    timeout_seconds: float = 5.0,
    git_executable: str = "git",
) -> GitContext:
    if output_limit < 32:
        raise ValueError("output_limit must be at least 32 bytes")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    try:
        working_directory = Path(directory).resolve(strict=True)
    except OSError:
        return _empty_context("workspace is unavailable")
    if not working_directory.is_dir():
        return _empty_context("workspace is unavailable")

    trusted_executable = _resolve_executable(git_executable)
    if trusted_executable is None:
        return _empty_context("git is unavailable")

    root_result = _run_git(
        working_directory,
        ["rev-parse", "--show-toplevel"],
        trusted_executable,
        timeout_seconds,
        16_384,
    )
    if root_result is None:
        return _empty_context("git is unavailable")
    if root_result.exit_code != 0:
        return _empty_context("not a git repository")

    root_text = root_result.stdout.strip()
    try:
        root = Path(root_text).resolve(strict=True)
    except OSError:
        return _empty_context("repository root is unavailable")
    try:
        selected = working_directory.relative_to(root)
    except ValueError:
        return _empty_context("repository root is unavailable")
    pathspec = "." if not selected.parts else f":(top,literal){selected.as_posix()}"

    branch = _branch(root, trusted_executable, timeout_seconds)
    owner, repository = _origin(root, trusted_executable, timeout_seconds)
    status_result = _run_git(
        root,
        [
            "status",
            "--porcelain=v1",
            "--untracked-files=normal",
            "--",
            pathspec,
        ],
        trusted_executable,
        timeout_seconds,
        output_limit,
    )
    diff_result = _run_git(
        root,
        [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "--unified=1",
            "HEAD",
            "--",
            pathspec,
        ],
        trusted_executable,
        timeout_seconds,
        output_limit,
    )
    if status_result is None or diff_result is None:
        return GitContext(True, str(root), branch, False, owner, repository, "", "", "git command timed out")

    status = status_result.stdout.rstrip("\r\n")
    diff = diff_result.stdout.rstrip("\r\n")
    error = None
    if status_result.exit_code != 0 or diff_result.exit_code != 0:
        error = "git context is incomplete"
    return GitContext(
        True,
        str(root),
        branch,
        bool(status),
        owner,
        repository,
        status,
        diff,
        error,
    )


def _empty_context(error: str) -> GitContext:
    return GitContext(False, None, None, False, None, None, "", "", error)


def _resolve_executable(requested: str) -> str | None:
    requested_path = Path(requested)
    if requested_path.is_absolute():
        return str(requested_path.resolve()) if requested_path.is_file() else None
    if requested_path.parent != Path("."):
        return None

    if os.name == "nt" and not requested_path.suffix:
        names = [requested + extension for extension in (".EXE", ".COM")]
    else:
        names = [requested]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry:
            continue
        directory = Path(entry)
        if not directory.is_absolute():
            continue
        for name in names:
            candidate = directory / name
            if candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK)):
                return str(candidate.resolve())
    return None


def _branch(root: Path, executable: str, timeout: float) -> str | None:
    symbolic = _run_git(root, ["symbolic-ref", "--quiet", "--short", "HEAD"], executable, timeout, 1024)
    if symbolic is not None and symbolic.exit_code == 0:
        return symbolic.stdout.strip() or None
    revision = _run_git(root, ["rev-parse", "--short", "HEAD"], executable, timeout, 1024)
    if revision is not None and revision.exit_code == 0 and revision.stdout.strip():
        return f"(detached at {revision.stdout.strip()})"
    return None


def _origin(root: Path, executable: str, timeout: float) -> tuple[str | None, str | None]:
    result = _run_git(root, ["remote", "get-url", "origin"], executable, timeout, 4096)
    if result is None or result.exit_code != 0:
        return None, None
    return _parse_origin(result.stdout.strip())


def _parse_origin(origin: str) -> tuple[str | None, str | None]:
    if "://" in origin:
        path = urlsplit(origin).path
    elif ":" in origin and not re.match(r"^[A-Za-z]:[\\/]", origin):
        path = origin.split(":", 1)[1]
    else:
        path = origin
    segments = [unquote(segment) for segment in path.replace("\\", "/").split("/") if segment]
    if len(segments) < 2:
        return None, None
    owner = segments[-2]
    repository = segments[-1]
    if repository.endswith(".git"):
        repository = repository[:-4]
    safe_component = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not safe_component.fullmatch(owner) or not safe_component.fullmatch(repository):
        return None, None
    return owner, repository


def _run_git(
    cwd: Path,
    arguments: list[str],
    executable: str,
    timeout: float,
    output_limit: int,
) -> _CommandResult | None:
    environment = os.environ.copy()
    environment.update(
        {
            "GCM_INTERACTIVE": "never",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    try:
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            completed = subprocess.run(
                [
                    executable,
                    "--no-optional-locks",
                    "-c",
                    "core.fsmonitor=false",
                    *arguments,
                ],
                cwd=cwd,
                env=environment,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout,
                shell=False,
                check=False,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt"
                    else 0
                ),
            )
            stdout_file.seek(0)
            stdout = _decode_limited(stdout_file.read(output_limit + 1), output_limit)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return _CommandResult(completed.returncode, stdout)


def _decode_limited(data: bytes, limit: int) -> str:
    if len(data) <= limit:
        return data.decode("utf-8", errors="replace")
    marker = b"\n[truncated]"
    prefix_limit = max(0, limit - len(marker))
    prefix = data[:prefix_limit].decode("utf-8", errors="ignore")
    return prefix + marker.decode("ascii")
