"""Read-only Vortex inventory for ChatMPD specialist routing."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def _default_root() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Vortex"


@dataclass(frozen=True)
class VortexGame:
    game_id: str
    profile_count: int
    mod_count: int
    snapshot_entries: int
    snapshot_base_paths: tuple[str, ...]


@dataclass(frozen=True)
class VortexReport:
    root: Path
    version: str
    games: tuple[VortexGame, ...]


class VortexInventory:
    """Summarize Vortex-managed state without touching live deployment databases."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or _default_root())

    def scan(self) -> VortexReport:
        if not self.root.is_dir():
            raise FileNotFoundError(f"Vortex state directory was not found: {self.root}")
        version = "unknown"
        startup = self.root / "startup.json"
        if startup.is_file() and startup.stat().st_size <= 1_048_576:
            try:
                payload = json.loads(startup.read_text("utf-8"))
                version = str(payload.get("storeVersion", "unknown"))
            except (OSError, json.JSONDecodeError, AttributeError):
                version = "unknown"

        games: list[VortexGame] = []
        for candidate in sorted(self.root.iterdir(), key=lambda item: item.name.casefold()):
            if not candidate.is_dir():
                continue
            if not any((candidate / name).is_dir() for name in ("mods", "profiles", "snapshots")):
                continue
            games.append(self._scan_game(candidate))
        return VortexReport(self.root, version, tuple(games))

    @staticmethod
    def _count_children(path: Path) -> int:
        if not path.is_dir():
            return 0
        try:
            return sum(1 for item in path.iterdir() if item.name != "__vortex_staging_folder")
        except OSError:
            return 0

    def _scan_game(self, game: Path) -> VortexGame:
        bases: list[str] = []
        entries = 0
        snapshot = game / "snapshots" / "snapshot.json"
        if snapshot.is_file() and snapshot.stat().st_size <= 64 * 1024 * 1024:
            try:
                payload = json.loads(snapshot.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = []
            if isinstance(payload, list):
                for section in payload[:512]:
                    if not isinstance(section, dict):
                        continue
                    base = str(section.get("basePath", "")).strip()
                    if base:
                        bases.append(base)
                    values = section.get("entries", [])
                    if isinstance(values, list):
                        entries += len(values)
        return VortexGame(
            game_id=game.name,
            profile_count=self._count_children(game / "profiles"),
            mod_count=self._count_children(game / "mods"),
            snapshot_entries=entries,
            snapshot_base_paths=tuple(bases),
        )
