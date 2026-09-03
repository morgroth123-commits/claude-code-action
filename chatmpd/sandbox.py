from __future__ import annotations

import os
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable


_PROBE_COMMAND = (
    "/usr/bin/bwrap",
    "--die-with-parent",
    "--unshare-user",
    "--unshare-pid",
    "--unshare-net",
    "--ro-bind",
    "/usr",
    "/usr",
    "--ro-bind",
    "/lib",
    "/lib",
    "--ro-bind",
    "/lib64",
    "/lib64",
    "--proc",
    "/proc",
    "--dev",
    "/dev",
    "/usr/bin/true",
)

_GUEST_LAUNCH_SCRIPT = r"""
set -eu
root=$1
duration=$2
shift 2
case "$root" in
    /tmp/chatmpd-sandbox-[0-9a-f]*) ;;
    *) echo "invalid ChatMPD sandbox path" >&2; exit 125 ;;
esac
umask 077
/usr/bin/mkdir -- "$root"
cleanup() {
    /usr/bin/rm -rf -- "$root"
}
trap cleanup EXIT HUP INT TERM
/usr/bin/mkdir -- "$root/work"
/usr/bin/tar --extract --file=- --directory="$root/work" \
    --no-same-owner --no-same-permissions --numeric-owner
set +e
/usr/bin/timeout --signal=TERM --kill-after=1s "$duration" \
    /usr/bin/bwrap \
    --die-with-parent \
    --new-session \
    --unshare-user \
    --unshare-pid \
    --unshare-net \
    --unshare-ipc \
    --unshare-uts \
    --cap-drop ALL \
    --ro-bind /usr /usr \
    --ro-bind /lib /lib \
    --ro-bind /lib64 /lib64 \
    --symlink usr/bin /bin \
    --symlink usr/sbin /sbin \
    --proc /proc \
    --dev /dev \
    --dir /etc \
    --dir /home \
    --dir /run \
    --tmpfs /tmp \
    --bind "$root/work" /work \
    --chdir /work \
    --clearenv \
    --setenv HOME /tmp \
    --setenv LANG C.UTF-8 \
    --setenv LC_ALL C.UTF-8 \
    --setenv PATH /usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    --setenv PYTHONDONTWRITEBYTECODE 1 \
    --setenv PYTHONPYCACHEPREFIX /tmp/pycache \
    --setenv TMPDIR /tmp \
    -- "$@"
status=$?
set -e
exit "$status"
"""

_EXCLUDED_DIRECTORY_NAMES = frozenset(
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

_EXCLUDED_FILE_NAMES = frozenset(
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

_EXCLUDED_FILE_SUFFIXES = frozenset({".key", ".p12", ".pem", ".pfx"})


@dataclass(frozen=True)
class SandboxHealth:
    available: bool
    detail: str


@dataclass(frozen=True)
class SandboxResult:
    status: str
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    output_truncated: bool
    snapshot_files: int
    snapshot_bytes: int
    error: str | None


class _SnapshotRejected(RuntimeError):
    pass


class _OutputBudget:
    def __init__(self, limit_bytes: int) -> None:
        self._remaining = limit_bytes
        self._streams = {"stdout": bytearray(), "stderr": bytearray()}
        self._lock = threading.Lock()
        self.truncated = False

    def append(self, stream_name: str, data: bytes) -> None:
        with self._lock:
            accepted = data[: self._remaining]
            self._streams[stream_name].extend(accepted)
            self._remaining -= len(accepted)
            if len(accepted) != len(data):
                self.truncated = True

    def text(self, stream_name: str) -> str:
        return bytes(self._streams[stream_name]).decode("utf-8", errors="replace")


class SandboxRunner:
    """Run Linux argv in a disposable WSL2 + bubblewrap project snapshot."""

    def __init__(
        self,
        *,
        distro: str = "Ubuntu",
        wsl_executable: str = "wsl.exe",
        max_snapshot_bytes: int = 256 * 1024 * 1024,
        max_snapshot_files: int = 20_000,
        max_file_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.distro = distro
        self.wsl_executable = wsl_executable
        self.max_snapshot_bytes = max_snapshot_bytes
        self.max_snapshot_files = max_snapshot_files
        self.max_file_bytes = max_file_bytes
        self._health: SandboxHealth | None = None

    def probe(self, *, refresh: bool = False) -> SandboxHealth:
        if self._health is not None and not refresh:
            return self._health
        command = [
            self.wsl_executable,
            "-d",
            self.distro,
            "--exec",
            *_PROBE_COMMAND,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
                check=False,
                creationflags=self._creation_flags(),
            )
        except FileNotFoundError:
            health = SandboxHealth(False, "WSL executable was not found")
        except subprocess.TimeoutExpired:
            health = SandboxHealth(False, "WSL sandbox probe timed out")
        except OSError as error:
            health = SandboxHealth(False, f"WSL sandbox probe failed: {error}")
        else:
            if completed.returncode == 0:
                health = SandboxHealth(
                    True,
                    f"WSL distro {self.distro!r} and bubblewrap are healthy",
                )
            else:
                detail = (completed.stderr or completed.stdout).strip()[-2_000:]
                health = SandboxHealth(
                    False,
                    f"WSL sandbox probe failed ({completed.returncode}): {detail}",
                )
        self._health = health
        return health

    def run(
        self,
        workspace: Path,
        argv: list[str],
        *,
        timeout_seconds: float = 60,
        output_limit_bytes: int = 64 * 1024,
    ) -> SandboxResult:
        operation_started = time.monotonic()
        requested_argv = [str(argument) for argument in argv]
        health = self.probe()
        if not health.available:
            return self._result(
                status="unavailable",
                argv=requested_argv,
                started=operation_started,
                error=health.detail,
            )

        validation_error = self._validate_request(
            workspace, requested_argv, timeout_seconds, output_limit_bytes
        )
        if validation_error is not None:
            return self._result(
                status="rejected",
                argv=requested_argv,
                started=operation_started,
                error=validation_error,
            )

        resolved_workspace = workspace.resolve(strict=True)
        snapshot_files = 0
        snapshot_bytes = 0
        with tempfile.TemporaryFile(mode="w+b") as archive:
            try:
                snapshot_files, snapshot_bytes = self._write_snapshot(
                    resolved_workspace, archive
                )
            except (OSError, _SnapshotRejected, tarfile.TarError) as error:
                return self._result(
                    status="rejected",
                    argv=requested_argv,
                    started=operation_started,
                    error=f"Workspace snapshot was rejected: {error}",
                )
            archive.seek(0)
            return self._launch(
                archive=archive,
                argv=requested_argv,
                timeout_seconds=timeout_seconds,
                output_limit_bytes=output_limit_bytes,
                operation_started=operation_started,
                snapshot_files=snapshot_files,
                snapshot_bytes=snapshot_bytes,
            )

    def _launch(
        self,
        *,
        archive: BinaryIO,
        argv: list[str],
        timeout_seconds: float,
        output_limit_bytes: int,
        operation_started: float,
        snapshot_files: int,
        snapshot_bytes: int,
    ) -> SandboxResult:
        sandbox_root = f"/tmp/chatmpd-sandbox-{uuid.uuid4().hex}"
        duration = f"{timeout_seconds:.3f}s"
        command = [
            self.wsl_executable,
            "-d",
            self.distro,
            "--exec",
            "/bin/sh",
            "-c",
            _GUEST_LAUNCH_SCRIPT,
            "chatmpd-sandbox",
            sandbox_root,
            duration,
            *argv,
        ]
        budget = _OutputBudget(output_limit_bytes)
        try:
            process = subprocess.Popen(
                command,
                stdin=archive,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=self._creation_flags(),
            )
        except (OSError, ValueError) as error:
            return self._result(
                status="unavailable",
                argv=argv,
                started=operation_started,
                snapshot_files=snapshot_files,
                snapshot_bytes=snapshot_bytes,
                error=f"WSL sandbox could not start: {error}",
            )

        readers = [
            threading.Thread(
                target=self._drain,
                args=(process.stdout, budget, "stdout"),
                daemon=True,
            ),
            threading.Thread(
                target=self._drain,
                args=(process.stderr, budget, "stderr"),
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()

        outer_timeout = timeout_seconds + 5
        outer_timed_out = False
        try:
            process.wait(timeout=outer_timeout)
        except subprocess.TimeoutExpired:
            outer_timed_out = True
            self._terminate_process_tree(process)
            self._cleanup_guest_root(sandbox_root)
        finally:
            for reader in readers:
                reader.join(timeout=2)

        exit_code = process.returncode
        timed_out = outer_timed_out or exit_code in {124, 137}
        status = "timed_out" if timed_out else "completed"
        error = (
            f"Sandbox command exceeded {timeout_seconds:g} seconds"
            if timed_out
            else None
        )
        return self._result(
            status=status,
            argv=argv,
            started=operation_started,
            exit_code=exit_code,
            stdout=budget.text("stdout"),
            stderr=budget.text("stderr"),
            timed_out=timed_out,
            output_truncated=budget.truncated,
            snapshot_files=snapshot_files,
            snapshot_bytes=snapshot_bytes,
            error=error,
        )

    def _write_snapshot(self, workspace: Path, archive: BinaryIO) -> tuple[int, int]:
        file_count = 0
        byte_count = 0
        with tarfile.open(fileobj=archive, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for path, relative in self._snapshot_files(workspace):
                with path.open("rb") as stream:
                    metadata = os.fstat(stream.fileno())
                    if not stat.S_ISREG(metadata.st_mode):
                        continue
                    if metadata.st_size > self.max_file_bytes:
                        raise _SnapshotRejected(
                            f"{relative.as_posix()} exceeds the per-file limit"
                        )
                    file_count += 1
                    byte_count += metadata.st_size
                    if file_count > self.max_snapshot_files:
                        raise _SnapshotRejected("workspace contains too many files")
                    if byte_count > self.max_snapshot_bytes:
                        raise _SnapshotRejected("workspace snapshot is too large")
                    info = tarfile.TarInfo(relative.as_posix())
                    info.size = metadata.st_size
                    info.mode = stat.S_IMODE(metadata.st_mode) or 0o600
                    info.mtime = int(metadata.st_mtime)
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    tar.addfile(info, stream)
        return file_count, byte_count

    def _snapshot_files(self, workspace: Path) -> Iterable[tuple[Path, Path]]:
        pending = [workspace]
        is_junction = getattr(os.path, "isjunction", lambda _path: False)
        while pending:
            directory = pending.pop()
            try:
                entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
            except OSError as error:
                raise _SnapshotRejected(f"cannot read {directory}: {error}") from error
            for entry in entries:
                name = entry.name
                lowered_name = name.casefold()
                entry_path = Path(entry.path)
                if entry.is_symlink() or is_junction(entry.path):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if lowered_name not in _EXCLUDED_DIRECTORY_NAMES:
                            pending.append(entry_path)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                relative = entry_path.relative_to(workspace)
                if self._is_excluded_file(relative):
                    continue
                resolved = entry_path.resolve(strict=True)
                if workspace != resolved and workspace not in resolved.parents:
                    continue
                yield entry_path, relative

    @staticmethod
    def _is_excluded_file(relative: Path) -> bool:
        name = relative.name.casefold()
        if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
            return True
        if name in _EXCLUDED_FILE_NAMES:
            return True
        return relative.suffix.casefold() in _EXCLUDED_FILE_SUFFIXES

    @staticmethod
    def _validate_request(
        workspace: Path,
        argv: list[str],
        timeout_seconds: float,
        output_limit_bytes: int,
    ) -> str | None:
        if not workspace.exists() or not workspace.is_dir():
            return "Workspace must be an existing directory"
        if not argv or not argv[0]:
            return "A non-empty argv command is required"
        if any("\x00" in argument for argument in argv):
            return "Command arguments cannot contain NUL bytes"
        if sum(len(argument) for argument in argv) > 24_000:
            return "Command arguments exceed the Windows launcher limit"
        if not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 3_600:
            return "Timeout must be greater than zero and no more than one hour"
        if not isinstance(output_limit_bytes, int) or not 0 < output_limit_bytes <= 16 * 1024 * 1024:
            return "Output limit must be between 1 byte and 16 MiB"
        return None

    @staticmethod
    def _drain(
        pipe: BinaryIO | None, budget: _OutputBudget, stream_name: str
    ) -> None:
        if pipe is None:
            return
        try:
            while True:
                chunk = pipe.read(65_536)
                if not chunk:
                    return
                budget.append(stream_name, chunk)
        finally:
            pipe.close()

    def _terminate_process_tree(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=3,
                    shell=False,
                    check=False,
                    creationflags=self._creation_flags(),
                )
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
        else:
            process.kill()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()

    def _cleanup_guest_root(self, sandbox_root: str) -> None:
        if not sandbox_root.startswith("/tmp/chatmpd-sandbox-"):
            return
        try:
            subprocess.run(
                [
                    self.wsl_executable,
                    "-d",
                    self.distro,
                    "--exec",
                    "/usr/bin/rm",
                    "-rf",
                    "--",
                    sandbox_root,
                ],
                capture_output=True,
                timeout=3,
                shell=False,
                check=False,
                creationflags=self._creation_flags(),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    @staticmethod
    def _creation_flags() -> int:
        if os.name != "nt":
            return 0
        return subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP

    @staticmethod
    def _result(
        *,
        status: str,
        argv: list[str],
        started: float,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
        timed_out: bool = False,
        output_truncated: bool = False,
        snapshot_files: int = 0,
        snapshot_bytes: int = 0,
        error: str | None = None,
    ) -> SandboxResult:
        return SandboxResult(
            status=status,
            argv=list(argv),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=time.monotonic() - started,
            timed_out=timed_out,
            output_truncated=output_truncated,
            snapshot_files=snapshot_files,
            snapshot_bytes=snapshot_bytes,
            error=error,
        )
