"""Managed reversible file snapshots for ChatMPD-owned changes."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from .platform_db import PlatformDatabase
from .platform_paths import PlatformPaths


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class RecoveryEntry:
    target: Path
    backup: Path
    sha256: str


@dataclass(frozen=True)
class RecoverySnapshot:
    snapshot_id: str
    label: str
    created_at: str
    entries: tuple[RecoveryEntry, ...]


class RecoveryCenter:
    def __init__(
        self,
        database: PlatformDatabase | None = None,
        root: Path | None = None,
    ) -> None:
        self.database = database or PlatformDatabase()
        self.root = Path(root or (PlatformPaths.default().data / "recovery"))
        self.root.mkdir(parents=True, exist_ok=True)

    def snapshot(self, paths: Iterable[Path], *, label: str) -> RecoverySnapshot:
        clean_label = " ".join(str(label).split()).strip()
        if not clean_label:
            raise ValueError("Recovery snapshot label is required.")
        targets = [Path(item).expanduser().resolve() for item in paths]
        if not targets:
            raise ValueError("At least one file is required for a recovery snapshot.")
        for target in targets:
            if not target.is_file():
                raise ValueError(f"Recovery target must be an existing file: {target}")

        snapshot_id = uuid4().hex
        folder = self.root / snapshot_id
        folder.mkdir(parents=True, exist_ok=False)
        entries: list[RecoveryEntry] = []
        for index, target in enumerate(targets):
            digest = _sha256(target)
            safe_name = "".join(ch if ch.isalnum() or ch in ".-_" else "_" for ch in target.name)
            backup = folder / f"{index:03d}_{digest[:12]}_{safe_name}"
            shutil.copy2(target, backup)
            entries.append(RecoveryEntry(target, backup, digest))
        snapshot = RecoverySnapshot(
            snapshot_id,
            clean_label[:160],
            datetime.now(UTC).isoformat(),
            tuple(entries),
        )
        self._write(snapshot)
        return snapshot

    def get(self, snapshot_id: str) -> RecoverySnapshot:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? AND record_id=?",
                ("recovery", str(snapshot_id)),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown recovery snapshot: {snapshot_id}")
        return self._decode(str(row["payload"]))

    def list(self, *, limit: int = 100) -> tuple[RecoverySnapshot, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? ORDER BY updated_at DESC LIMIT ?",
                ("recovery", max(1, min(int(limit), 500))),
            ).fetchall()
        return tuple(self._decode(str(row["payload"])) for row in rows)

    def rollback(self, snapshot_id: str) -> tuple[Path, ...]:
        snapshot = self.get(snapshot_id)
        restored: list[Path] = []
        for entry in snapshot.entries:
            if not entry.backup.is_file() or _sha256(entry.backup) != entry.sha256:
                raise RuntimeError(f"Recovery backup failed integrity check: {entry.backup}")
            entry.target.parent.mkdir(parents=True, exist_ok=True)
            temporary = entry.target.with_name(entry.target.name + ".chatmpd-restore")
            shutil.copy2(entry.backup, temporary)
            temporary.replace(entry.target)
            restored.append(entry.target)
        return tuple(restored)

    def _write(self, snapshot: RecoverySnapshot) -> None:
        payload = json.dumps({
            "snapshot_id": snapshot.snapshot_id,
            "label": snapshot.label,
            "created_at": snapshot.created_at,
            "entries": [
                {"target": str(item.target), "backup": str(item.backup), "sha256": item.sha256}
                for item in snapshot.entries
            ],
        })
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO platform_records(namespace, record_id, payload, updated_at) VALUES (?, ?, ?, ?)",
                ("recovery", snapshot.snapshot_id, payload, snapshot.created_at),
            )
            connection.commit()

    @staticmethod
    def _decode(payload: str) -> RecoverySnapshot:
        data = json.loads(payload)
        entries = tuple(
            RecoveryEntry(
                Path(str(item["target"])),
                Path(str(item["backup"])),
                str(item["sha256"]),
            )
            for item in data.get("entries", [])
        )
        return RecoverySnapshot(
            str(data["snapshot_id"]),
            str(data["label"]),
            str(data["created_at"]),
            entries,
        )
