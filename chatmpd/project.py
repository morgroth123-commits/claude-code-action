from __future__ import annotations

import ast
import heapq
import os
from dataclasses import dataclass
from pathlib import Path

from .git_context import GitContext, collect_git_context


_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".aws",
        ".azure",
        ".cache",
        ".chatmpd",
        ".git",
        ".hg",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".secrets",
        ".ssh",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "cache",
        "caches",
        "dist",
        "node_modules",
        "secret",
        "secrets",
        "venv",
    }
)

_EXCLUDED_FILES = frozenset(
    {
        ".netrc",
        ".npmrc",
        ".pypirc",
        "credentials.json",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "service-account.json",
    }
)


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    bytes: int


@dataclass(frozen=True)
class _ManifestScan:
    entries: list[ManifestEntry]
    truncated: bool
    has_python: bool
    has_unittest: bool


@dataclass(frozen=True)
class SafeGitContext:
    is_repository: bool
    branch: str | None
    origin: str | None
    dirty: bool
    status: str
    diff: str
    error: str | None


@dataclass(frozen=True)
class ProjectProfile:
    project_type: str
    supported: bool
    detail: str
    manifest: list[ManifestEntry]
    manifest_truncated: bool
    git: SafeGitContext
    verification_commands: list[list[str]]
    required_checks: list[list[str]]


def profile_project(
    workspace: Path,
    *,
    max_inventory_files: int = 500,
) -> ProjectProfile:
    root = Path(workspace).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Project workspace is not a directory: {root}")

    scan = _safe_manifest(root, max_inventory_files)
    git = _safe_git_context(collect_git_context(root, output_limit=16_384))
    if scan.has_unittest:
        command = [
            "/usr/bin/python3",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
        ]
        return ProjectProfile(
            "python-unittest",
            True,
            "Python unittest project",
            scan.entries,
            scan.truncated,
            git,
            [command],
            [list(command)],
        )
    if scan.has_python:
        command = ["/usr/bin/python3", "-m", "compileall", "-q", "."]
        return ProjectProfile(
            "python-syntax",
            True,
            "Python project with syntax verification",
            scan.entries,
            scan.truncated,
            git,
            [command],
            [list(command)],
        )
    return ProjectProfile(
        "unsupported",
        False,
        "Unsupported project: no safe offline verification command was identified.",
        scan.entries,
        scan.truncated,
        git,
        [],
        [],
    )


def _safe_manifest(root: Path, limit: int) -> _ManifestScan:
    files: list[ManifestEntry] = []
    pending: list[tuple[str, str, os.DirEntry[str]]] = []
    has_python = False
    has_unittest = False
    truncated = False
    is_junction = getattr(os.path, "isjunction", lambda _path: False)

    def add_directory(directory: Path) -> None:
        try:
            entries = os.scandir(directory)
            with entries:
                for entry in entries:
                    try:
                        relative = Path(entry.path).relative_to(root).as_posix()
                    except ValueError:
                        continue
                    heapq.heappush(
                        pending,
                        (relative.casefold(), relative, entry),
                    )
        except OSError:
            return

    add_directory(root)
    while pending:
        _, relative_text, entry = heapq.heappop(pending)
        entry_path = Path(entry.path)
        if entry.is_symlink() or is_junction(entry.path):
            continue
        try:
            if entry.is_dir(follow_symlinks=False):
                if entry.name.casefold() not in _EXCLUDED_DIRECTORIES:
                    add_directory(entry_path)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            relative = Path(relative_text)
            if _is_sensitive_file(relative):
                continue
            resolved = entry_path.resolve(strict=True)
            if root != resolved and root not in resolved.parents:
                continue
            size = entry.stat(follow_symlinks=False).st_size
        except OSError:
            continue
        if relative.suffix.casefold() == ".py":
            has_python = True
            if not has_unittest and _is_recognizable_unittest(relative, entry_path):
                has_unittest = True
        if len(files) >= limit:
            truncated = True
            break
        files.append(ManifestEntry(relative.as_posix(), size))
    return _ManifestScan(
        files,
        truncated,
        has_python,
        has_unittest,
    )


def _is_recognizable_unittest(relative: Path, source_path: Path) -> bool:
    if (
        len(relative.parts) < 2
        or relative.parts[0] != "tests"
        or relative.suffix.casefold() != ".py"
        or not relative.name.casefold().startswith("test")
    ):
        return False
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError):
        return False

    module_names: set[str] = set()
    case_names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "unittest":
                    module_names.add(alias.asname or "unittest")
        elif isinstance(node, ast.ImportFrom) and node.module == "unittest":
            for alias in node.names:
                if alias.name in {"TestCase", "IsolatedAsyncioTestCase"}:
                    case_names.add(alias.asname or alias.name)

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        is_test_case = any(
            (
                isinstance(base, ast.Name)
                and base.id in case_names
            )
            or (
                isinstance(base, ast.Attribute)
                and isinstance(base.value, ast.Name)
                and base.value.id in module_names
                and base.attr in {"TestCase", "IsolatedAsyncioTestCase"}
            )
            for base in node.bases
        )
        if is_test_case and any(
            isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and member.name.startswith("test")
            for member in node.body
        ):
            return True
    return False


def _is_sensitive_file(relative: Path) -> bool:
    name = relative.name.casefold()
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return True
    if name in _EXCLUDED_FILES:
        return True
    return relative.suffix.casefold() in {".key", ".p12", ".pem", ".pfx"}


def _safe_git_context(context: GitContext) -> SafeGitContext:
    origin = None
    if context.origin_owner and context.origin_repo:
        origin = f"{context.origin_owner}/{context.origin_repo}"
    return SafeGitContext(
        is_repository=context.is_repository,
        branch=_bounded_single_line(context.branch, 512),
        origin=origin,
        dirty=context.dirty,
        status=_sanitize_status(context.status),
        diff=_sanitize_diff(context.diff),
        error=_bounded_single_line(context.error, 1_024),
    )


def _bounded_single_line(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    cleaned = "".join(character for character in value if ord(character) >= 32)
    return cleaned[:limit] or None


def _sanitize_status(status: str) -> str:
    safe_lines = [
        line
        for line in status.splitlines()
        if not _line_mentions_sensitive_path(line[3:] if len(line) >= 3 else line)
    ]
    return "\n".join(safe_lines)


def _sanitize_diff(diff: str) -> str:
    if not diff:
        return ""
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in diff.splitlines():
        if line.startswith("diff --git ") and current:
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)
    safe_blocks = [
        "\n".join(block)
        for block in blocks
        if not any(
            _line_mentions_sensitive_path(line)
            for line in block
            if line.startswith(
                (
                    "diff --git ",
                    "--- ",
                    "+++ ",
                    "rename from ",
                    "rename to ",
                    "Binary files ",
                )
            )
        )
    ]
    return "\n".join(safe_blocks)


def _line_mentions_sensitive_path(text: str) -> bool:
    normalized = text.replace("\\", "/").replace('"', "")
    for raw_candidate in normalized.replace(" -> ", " ").split():
        candidate = raw_candidate.strip()
        if candidate.startswith(("a/", "b/")):
            candidate = candidate[2:]
        candidate = candidate.rstrip(":")
        if not candidate or candidate == "/dev/null":
            continue
        path = Path(candidate)
        if any(part.casefold() in _EXCLUDED_DIRECTORIES for part in path.parts):
            return True
        if _is_sensitive_file(path):
            return True
    return False
