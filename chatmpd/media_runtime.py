"""Managed local ComfyUI runtime for ChatMPD media work."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from .runtime import is_eso_running


@dataclass(frozen=True)
class ComfyUIServerProbe:
    healthy: bool
    detail: str = ""


def probe_comfyui_server(
    endpoint: str,
    timeout: float,
    *,
    opener: Any | None = None,
) -> ComfyUIServerProbe:
    http = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        request = urllib.request.Request(
            f"{endpoint.rstrip('/')}/system_stats", method="GET"
        )
        with http.open(request, timeout=timeout) as response:
            payload = json.loads(response.read(262_144))
            if response.status != 200 or not isinstance(payload, dict):
                return ComfyUIServerProbe(False, "unexpected response")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ComfyUIServerProbe(False, type(exc).__name__)
    if "system" not in payload and "devices" not in payload:
        return ComfyUIServerProbe(False, "not ComfyUI")
    return ComfyUIServerProbe(True, "ready")


@dataclass(frozen=True)
class MediaRuntimeConfig:
    root: Path = Path(r"D:\ChatMPD\media\ComfyUI-Installs\ComfyUI")
    models_dir: Path = Path(r"D:\ChatMPD\media\ComfyUI-Shared\models")
    input_dir: Path = Path(r"D:\ChatMPD\media\ComfyUI-Shared\input")
    output_dir: Path = Path(r"D:\ChatMPD\media\ComfyUI-Shared\output")
    user_dir: Path = Path(r"D:\ChatMPD\media\ComfyUI-Shared\user")
    state_dir: Path = Path.home() / "AppData" / "Local" / "ChatMPD" / "media-runtime"
    endpoint: str = "http://127.0.0.1:8188"
    health_timeout: float = 1.0
    startup_timeout: float = 120.0
    poll_interval: float = 0.25

    def __post_init__(self) -> None:
        parsed = urllib.parse.urlsplit(self.endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.port is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("ComfyUI endpoint must be a plain HTTP loopback URL with a port")
        if self.startup_timeout <= 0 or self.poll_interval < 0:
            raise ValueError("Invalid media runtime timing configuration.")


@dataclass(frozen=True)
class MediaRuntimeDiagnostics:
    python_path: Path | None
    main_path: Path | None
    endpoint: str
    endpoint_healthy: bool
    eso_running: bool
    issues: tuple[str, ...]
    owned_server: bool = False
    pid: int | None = None
    log_path: Path | None = None


class MediaRuntime:
    def __init__(
        self,
        config: MediaRuntimeConfig | None = None,
        *,
        server_probe: Callable[[str, float], ComfyUIServerProbe] = probe_comfyui_server,
        eso_detector: Callable[[], bool] = is_eso_running,
        process_launcher: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or MediaRuntimeConfig()
        self._server_probe = server_probe
        self._eso_detector = eso_detector
        self._process_launcher = process_launcher or subprocess.Popen
        self._sleep = sleeper
        self._monotonic = monotonic
        self._owned_process: Any | None = None
        self._log_handle: Any | None = None
        self._log_path: Path | None = None

    @property
    def endpoint(self) -> str:
        return self.config.endpoint

    def __enter__(self) -> "MediaRuntime":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def diagnose(self) -> MediaRuntimeDiagnostics:
        portable_python = self.config.root / "python_embeded" / "python.exe"
        desktop_python = (
            self.config.root / "ComfyUI" / ".venv" / "Scripts" / "python.exe"
        )
        python_path = (
            portable_python
            if portable_python.is_file()
            else desktop_python if desktop_python.is_file() else None
        )
        main_path = self.config.root / "ComfyUI" / "main.py"
        probe = self._server_probe(self.config.endpoint, self.config.health_timeout)
        eso_running = self._eso_detector()
        issues: list[str] = []
        if python_path is None:
            issues.append("ComfyUI Python environment was not found")
        if not main_path.is_file():
            issues.append("ComfyUI main.py was not found")
            main_path = None
        return MediaRuntimeDiagnostics(
            python_path=python_path,
            main_path=main_path,
            endpoint=self.config.endpoint,
            endpoint_healthy=probe.healthy,
            eso_running=eso_running,
            issues=tuple(issues),
        )

    def start(self) -> MediaRuntimeDiagnostics:
        diagnostics = self.diagnose()
        if diagnostics.endpoint_healthy:
            return diagnostics
        if diagnostics.eso_running:
            raise RuntimeError("GPU media generation is paused while ESO is running.")
        if diagnostics.python_path is None or diagnostics.main_path is None:
            raise RuntimeError("; ".join(diagnostics.issues))
        for directory in (
            self.config.models_dir,
            self.config.input_dir,
            self.config.output_dir,
            self.config.user_dir,
            self.config.state_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        self._log_path = self.config.state_dir / "comfyui-server.log"
        self._log_handle = self._log_path.open("ab")
        command = self._build_command(diagnostics)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        creationflags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        environment = {
            key: value
            for key in (
                "SystemRoot", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATH",
                "USERPROFILE", "USERNAME", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA",
                "CUDA_PATH", "CUDA_PATH_V13_0", "NVIDIA_VISIBLE_DEVICES",
            )
            if (value := os.environ.get(key)) is not None
        }
        try:
            self._owned_process = self._process_launcher(
                command,
                stdin=subprocess.DEVNULL,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                cwd=str(self.config.root),
                env=environment,
                creationflags=creationflags,
            )
        except BaseException:
            self._close_log()
            raise

        deadline = self._monotonic() + self.config.startup_timeout
        while True:
            if self._owned_process.poll() is not None:
                log_path = self._log_path
                self._owned_process = None
                self._close_log()
                raise RuntimeError(f"ComfyUI exited during startup; see {log_path}")
            probe = self._server_probe(
                self.config.endpoint, self.config.health_timeout
            )
            if probe.healthy:
                return replace(
                    diagnostics,
                    endpoint_healthy=True,
                    owned_server=True,
                    pid=self._owned_process.pid,
                    log_path=self._log_path,
                    issues=(),
                )
            if self._monotonic() >= deadline:
                log_path = self._log_path
                self.stop()
                raise RuntimeError(f"ComfyUI startup timed out; see {log_path}")
            self._sleep(self.config.poll_interval)

    def stop(self) -> None:
        process = self._owned_process
        self._owned_process = None
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5.0)
        finally:
            self._close_log()

    def _build_command(self, diagnostics: MediaRuntimeDiagnostics) -> list[str]:
        assert diagnostics.python_path is not None
        assert diagnostics.main_path is not None
        port = urllib.parse.urlsplit(self.config.endpoint).port
        assert port is not None
        command = [
            str(diagnostics.python_path), "-s", str(diagnostics.main_path),
            "--disable-auto-launch",
            "--listen", "127.0.0.1", "--port", str(port),
            "--models-directory", str(self.config.models_dir),
            "--input-directory", str(self.config.input_dir),
            "--output-directory", str(self.config.output_dir),
            "--user-directory", str(self.config.user_dir),
            "--enable-dynamic-vram", "--async-offload", "2",
        ]
        if diagnostics.python_path.parent.name.casefold() == "python_embeded":
            command.insert(3, "--windows-standalone-build")
        return command

    def _close_log(self) -> None:
        handle = self._log_handle
        self._log_handle = None
        if handle is not None:
            handle.close()
