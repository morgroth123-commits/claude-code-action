"""Capability packs group related ChatMPD features without duplicating them."""

from __future__ import annotations

import json
import sys
import tomllib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from .platform_db import PlatformDatabase


def builtin_packs_root() -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "chatmpd" / "builtin_packs"
    return Path(__file__).resolve().parent / "builtin_packs"


@dataclass(frozen=True)
class CapabilityPack:
    pack_id: str
    name: str
    description: str
    capabilities: tuple[str, ...]
    installed: bool = False


class CapabilityPackManager:
    def __init__(self, root: Path | None = None, database: PlatformDatabase | None = None) -> None:
        self.root = Path(root or builtin_packs_root())
        self.database = database or PlatformDatabase()

    def list(self) -> tuple[CapabilityPack, ...]:
        if not self.root.is_dir():
            return ()
        return tuple(self._load(path) for path in sorted(self.root.glob("*.toml")))

    def get(self, pack_id: str) -> CapabilityPack:
        clean = str(pack_id).strip().casefold()
        for pack in self.list():
            if pack.pack_id.casefold() == clean:
                return pack
        raise KeyError(f"Unknown capability pack: {pack_id}")

    def install(self, pack_id: str) -> CapabilityPack:
        pack = self.get(pack_id)
        self._set_state(pack.pack_id, True)
        return replace(pack, installed=True)

    def uninstall(self, pack_id: str) -> bool:
        pack = self.get(pack_id)
        was_installed = pack.installed
        self._set_state(pack.pack_id, False)
        return was_installed

    def _installed(self, pack_id: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? AND record_id=?",
                ("pack", pack_id),
            ).fetchone()
        if row is None:
            return False
        return bool(json.loads(str(row["payload"])).get("installed"))

    def _set_state(self, pack_id: str, installed: bool) -> None:
        payload = json.dumps({"installed": bool(installed)})
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO platform_records(namespace, record_id, payload, updated_at) VALUES (?, ?, ?, ?)",
                ("pack", pack_id, payload, datetime.now(UTC).isoformat()),
            )
            connection.commit()

    def _load(self, path: Path) -> CapabilityPack:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        raw = data.get("pack")
        if not isinstance(raw, dict):
            raise ValueError(f"Capability pack requires [pack]: {path}")
        pack_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not pack_id or not name:
            raise ValueError(f"Capability pack requires id and name: {path}")
        values = raw.get("capabilities") or []
        if not isinstance(values, list):
            raise ValueError("pack.capabilities must be an array")
        capabilities = tuple(str(item).strip() for item in values if str(item).strip())
        return CapabilityPack(
            pack_id,
            name,
            str(raw.get("description") or "").strip(),
            capabilities,
            self._installed(pack_id),
        )
