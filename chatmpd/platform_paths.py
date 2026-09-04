"""Stable per-user storage locations for ChatMPD platform services."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def local_appdata_root() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    base = Path(value) if value else Path.home() / "AppData" / "Local"
    return base / "ChatMPD"


@dataclass(frozen=True)
class PlatformPaths:
    root: Path

    @classmethod
    def default(cls) -> "PlatformPaths":
        return cls(local_appdata_root())

    @property
    def extensions(self) -> Path:
        return self.root / "extensions"

    @property
    def data(self) -> Path:
        return self.root / "platform"

    @property
    def attachments(self) -> Path:
        return self.data / "attachments"

    @property
    def artifacts(self) -> Path:
        return self.data / "artifacts"

    @property
    def exports(self) -> Path:
        return self.root / "exports"

    @property
    def recovery(self) -> Path:
        return self.data / "recovery"
