"""Health checks and safe self-repair for ChatMPD-owned platform state."""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass
from pathlib import Path

from .extensions import ExtensionManager
from .platform_db import PlatformDatabase
from .platform_paths import PlatformPaths


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ready: bool
    detail: str
    optional: bool = False


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.ready or check.optional for check in self.checks)


class PlatformDoctor:
    def __init__(
        self,
        *,
        paths: PlatformPaths | None = None,
        extensions: ExtensionManager | None = None,
    ) -> None:
        self.paths = paths or PlatformPaths.default()
        self.extensions = extensions or ExtensionManager(self.paths.extensions)

    def run(self) -> DoctorReport:
        checks: list[DoctorCheck] = []
        checks.append(DoctorCheck(
            "managed-folders",
            self.paths.root.is_dir() and self.paths.extensions.is_dir() and self.paths.data.is_dir(),
            str(self.paths.root),
        ))
        try:
            PlatformDatabase(self.paths.data / "chatmpd.db")
            checks.append(DoctorCheck("database", True, "SQLite/FTS platform database ready."))
        except Exception as error:
            checks.append(DoctorCheck("database", False, f"{type(error).__name__}: {error}"))

        discovered = self.extensions.discover()
        broken = [item for item in discovered if item.health != "ready"]
        detail = f"{len(discovered)} extension(s), {len(broken)} unavailable."
        checks.append(DoctorCheck("extensions", not broken, detail))
        checks.append(DoctorCheck(
            "webview2-python",
            importlib.util.find_spec("webview") is not None,
            "pywebview is installed." if importlib.util.find_spec("webview") else "pywebview is missing.",
        ))
        checks.append(DoctorCheck(
            "ffmpeg",
            shutil.which("ffmpeg") is not None,
            shutil.which("ffmpeg") or "FFmpeg is not installed; video assembly will be unavailable.",
            optional=True,
        ))
        return DoctorReport(tuple(checks))

    def repair(self) -> tuple[str, ...]:
        actions: list[str] = []
        for path, label in (
            (self.paths.root, "created ChatMPD root"),
            (self.paths.extensions, "created extensions folder"),
            (self.paths.data, "created platform data folder"),
        ):
            if not path.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                actions.append(label)
        database_path = self.paths.data / "chatmpd.db"
        PlatformDatabase(database_path)
        actions.append("verified ChatMPD SQLite indexes")
        return tuple(actions)
