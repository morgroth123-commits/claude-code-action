"""Local LM Studio and Bionic integration for ChatMPD."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .llamacpp import LlamaCppProvider, ProviderError


@dataclass(frozen=True)
class LMStudioInstallation:
    lms_path: Path
    source: str


class LMStudioDiscovery:
    def __init__(self, extra_candidates: Iterable[Path] = ()) -> None:
        self.extra_candidates = tuple(Path(item) for item in extra_candidates)

    def discover(self) -> LMStudioInstallation | None:
        candidates = list(self.extra_candidates)
        command = shutil.which("lms")
        if command:
            candidates.append(Path(command))
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        candidates.extend([
            local / "Programs" / "LM Studio" / "resources" / "app" / ".webpack" / "lms.exe",
            local / "Programs" / "LM Studio" / "resources" / "app" / ".webpack-main" / "lms.exe",
            local / "Programs" / "Bionic" / "resources" / "app" / ".webpack-bionic" / "lms.exe",
        ])
        seen: set[Path] = set()
        for candidate in candidates:
            path = Path(candidate).expanduser()
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            source = "bionic-bundled-runtime" if "bionic" in str(path).casefold() else "lm-studio"
            return LMStudioInstallation(path, source)
        return None


class LMStudioProvider(LlamaCppProvider):
    """OpenAI-compatible client for a loopback LM Studio local server."""

    def health(self) -> bool:
        try:
            return bool(self.models())
        except ProviderError:
            return False


class BionicCompanion:
    def __init__(
        self,
        executable: Path | None = None,
        *,
        launcher: Callable[[list[str]], Any] | None = None,
    ) -> None:
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        self.executable = Path(executable) if executable else local / "Programs" / "Bionic" / "Bionic.exe"
        self._launcher = launcher or self._default_launcher

    def status(self) -> dict[str, Any]:
        return {
            "installed": self.executable.is_file(),
            "executable": str(self.executable),
            "cloud_enabled_by_chatmpd": False,
            "policy": "Local models only by default; paid/cloud use is never enabled silently.",
        }

    def open(self) -> None:
        if not self.executable.is_file() and self._launcher is self._default_launcher:
            raise FileNotFoundError(self.executable)
        self._launcher([str(self.executable)])

    @staticmethod
    def _default_launcher(argv: list[str]) -> None:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
