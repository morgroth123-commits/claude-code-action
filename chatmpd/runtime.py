from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable


def _default_state_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
    return base / "ChatMPD" / "runtime"


@dataclass(frozen=True)
class RuntimeConfig:
    server_path: Path | None = None
    model_path: Path | None = None
    cache_root: Path = Path(r"D:\ChatMPD\models\huggingface")
    state_dir: Path = _default_state_dir()
    endpoint: str = "http://127.0.0.1:8080"
    health_timeout: float = 1.0
    startup_timeout: float = 90.0
    poll_interval: float = 0.25
    context_size: int = 8192
    max_tokens: int = 512

    def __post_init__(self) -> None:
        if not 1 <= self.context_size <= 32_768:
            raise ValueError("context_size must be between 1 and 32768")
        if not 1 <= self.max_tokens <= 4_096:
            raise ValueError("max_tokens must be between 1 and 4096")
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
            raise ValueError("ChatMPD's llama.cpp endpoint must be a plain HTTP loopback URL with a port")


@dataclass(frozen=True)
class ServerProbe:
    healthy: bool
    is_chatmpd: bool
    detail: str = ""


def is_eso_running(*, command_runner: Callable[..., Any] = subprocess.run) -> bool:
    """Return whether the Elder Scrolls Online 64-bit client is running."""

    try:
        completed = command_runner(
            ["tasklist", "/FI", "IMAGENAME eq eso64.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return any(line.strip().lower().startswith('"eso64.exe",') for line in completed.stdout.splitlines())


def probe_chatmpd_server(
    endpoint: str,
    timeout: float,
    *,
    opener: Any | None = None,
) -> ServerProbe:
    """Check llama.cpp health and verify ChatMPD's private model alias."""

    http = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = endpoint.rstrip("/")
    try:
        health_request = urllib.request.Request(f"{base}/health", method="GET")
        with http.open(health_request, timeout=timeout) as response:
            health = json.loads(response.read(65_537))
            if response.status != 200 or health.get("status") != "ok":
                return ServerProbe(False, False, str(health.get("status", "unavailable")))
        models_request = urllib.request.Request(f"{base}/v1/models", method="GET")
        with http.open(models_request, timeout=timeout) as response:
            models = json.loads(response.read(65_537))
            if response.status != 200:
                return ServerProbe(True, False, "unexpected server")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ServerProbe(False, False, type(exc).__name__)
    aliases = {item.get("id") for item in models.get("data", []) if isinstance(item, dict)}
    return ServerProbe(True, "chatmpd-local" in aliases, "ready")


@dataclass(frozen=True)
class RuntimeDiagnostics:
    server_path: Path | None
    model_path: Path | None
    endpoint: str
    endpoint_healthy: bool
    endpoint_is_chatmpd: bool
    eso_running: bool
    mode: str
    issues: tuple[str, ...]
    owned_server: bool = False
    pid: int | None = None
    log_path: Path | None = None


class LlamaCppRuntime:
    def __init__(
        self,
        config: RuntimeConfig | None = None,
        *,
        server_probe: Callable[[str, float], ServerProbe] = probe_chatmpd_server,
        eso_detector: Callable[[], bool] = is_eso_running,
        process_launcher: Callable[..., Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or RuntimeConfig()
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

    def __enter__(self) -> "LlamaCppRuntime":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def diagnose(self) -> RuntimeDiagnostics:
        server = discover_llama_server(self.config.server_path)
        model = discover_qwen_model(self.config.model_path, cache_root=self.config.cache_root)
        probe = self._server_probe(self.config.endpoint, self.config.health_timeout)
        eso_running = self._eso_detector()
        issues: list[str] = []
        if server is None:
            issues.append("llama-server.exe was not found")
        if model is None:
            issues.append("Qwen2.5-Coder-7B Q4_K_M model was not found")
        return RuntimeDiagnostics(
            server_path=server,
            model_path=model,
            endpoint=self.config.endpoint,
            endpoint_healthy=probe.healthy,
            endpoint_is_chatmpd=probe.is_chatmpd,
            eso_running=eso_running,
            mode="cpu-safe" if eso_running else "gpu-auto",
            issues=tuple(issues),
        )

    def start(self) -> RuntimeDiagnostics:
        diagnostics = self.diagnose()
        if diagnostics.endpoint_healthy and diagnostics.endpoint_is_chatmpd:
            if self._owned_process is not None and self._owned_process.poll() is None:
                return replace(
                    diagnostics,
                    owned_server=True,
                    pid=self._owned_process.pid,
                    log_path=self._log_path,
                    issues=(),
                )
            raise RuntimeError(
                "The ChatMPD local model endpoint is already in use by another process"
            )
        if diagnostics.endpoint_healthy:
            raise RuntimeError("loopback endpoint is occupied by a non-ChatMPD server")
        if diagnostics.server_path is None or diagnostics.model_path is None:
            raise RuntimeError("; ".join(diagnostics.issues))

        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self.config.state_dir / "llama-server.log"
        self._log_handle = self._log_path.open("ab")
        command = self._build_command(diagnostics)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if diagnostics.eso_running:
            creationflags |= getattr(subprocess, "IDLE_PRIORITY_CLASS", 0)
        environment = {
            key: value
            for key in (
                "SystemRoot",
                "WINDIR",
                "COMSPEC",
                "TEMP",
                "TMP",
                "PATH",
                "USERPROFILE",
                "LOCALAPPDATA",
            )
            if (value := os.environ.get(key)) is not None
        }
        try:
            self._owned_process = self._process_launcher(
                command,
                stdin=subprocess.DEVNULL,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                cwd=str(diagnostics.server_path.parent),
                env=environment,
                creationflags=creationflags,
            )
        except BaseException:
            self._close_log()
            raise

        deadline = self._monotonic() + self.config.startup_timeout
        while True:
            if self._owned_process.poll() is not None:
                self._close_log()
                self._owned_process = None
                raise RuntimeError(f"llama.cpp exited during startup; see {self._log_path}")
            probe = self._server_probe(self.config.endpoint, self.config.health_timeout)
            if probe.healthy and probe.is_chatmpd:
                return replace(
                    diagnostics,
                    endpoint_healthy=True,
                    endpoint_is_chatmpd=True,
                    owned_server=True,
                    pid=self._owned_process.pid,
                    log_path=self._log_path,
                    issues=(),
                )
            if self._monotonic() >= deadline:
                log_path = self._log_path
                self.stop()
                raise RuntimeError(f"llama.cpp startup timed out; see {log_path}")
            self._sleep(self.config.poll_interval)

    def stop(self) -> None:
        process = self._owned_process
        self._owned_process = None
        try:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5.0)
        finally:
            self._close_log()

    def _build_command(self, diagnostics: RuntimeDiagnostics) -> list[str]:
        assert diagnostics.server_path is not None
        assert diagnostics.model_path is not None
        parsed = urllib.parse.urlsplit(self.config.endpoint)
        command = [
            str(diagnostics.server_path),
            "--model",
            str(diagnostics.model_path),
            "--alias",
            "chatmpd-local",
            "--host",
            "127.0.0.1",
            "--port",
            str(parsed.port),
            "--ctx-size",
            str(self.config.context_size),
            "--n-predict",
            str(self.config.max_tokens),
            "--parallel",
            "1",
            "--no-webui",
            "--cors-origins",
            "localhost",
            "--no-cors-credentials",
            "--jinja",
        ]
        if diagnostics.eso_running:
            command.extend(
                [
                    "--threads",
                    "1",
                    "--threads-batch",
                    "1",
                    "--n-gpu-layers",
                    "0",
                ]
            )
        else:
            command.extend(["--n-gpu-layers", "auto"])
        return command

    def _close_log(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None


def discover_llama_server(
    override: str | os.PathLike[str] | None = None,
    *,
    path_env: str | None = None,
    local_appdata: str | os.PathLike[str] | None = None,
) -> Path | None:
    """Return an explicitly configured llama.cpp server when it exists."""

    if override is None:
        located = shutil.which("llama-server.exe", path=path_env)
        if located:
            return Path(located).resolve()
        appdata = Path(local_appdata or os.environ.get("LOCALAPPDATA", ""))
        packages = appdata / "Microsoft" / "WinGet" / "Packages"
        for package in sorted(packages.glob("ggml.llamacpp_*")):
            matches = sorted(package.rglob("llama-server.exe"))
            if matches:
                return matches[0].resolve()
        return None
    candidate = Path(override).expanduser()
    return candidate.resolve() if candidate.is_file() else None


def discover_qwen_model(
    override: str | os.PathLike[str] | None = None,
    *,
    cache_root: str | os.PathLike[str] | None = None,
) -> Path | None:
    """Return an explicitly configured local GGUF model when it exists."""

    if override is not None:
        candidate = Path(override).expanduser()
        return candidate.absolute() if candidate.is_file() else None
    root = Path(cache_root or r"D:\ChatMPD\models\huggingface")
    matches = [
        item
        for item in root.rglob("*.gguf")
        if "qwen2.5-coder-7b-instruct" in item.name.lower()
        and "q4_k_m" in item.name.lower()
    ] if root.is_dir() else []
    for item in sorted(matches):
        split = re.match(r"^(.*)-(\d{5})-of-(\d{5})(\.gguf)$", item.name, re.IGNORECASE)
        if split is None:
            return item.absolute()
        prefix, raw_part, raw_total, suffix = split.groups()
        if int(raw_part) != 1:
            continue
        total = int(raw_total)
        if all(
            (item.parent / f"{prefix}-{part:05d}-of-{total:05d}{suffix}").is_file()
            for part in range(1, total + 1)
        ):
            return item.absolute()
    return None
