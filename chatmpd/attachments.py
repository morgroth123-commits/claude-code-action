"""Managed local attachment storage for ChatMPD conversations."""

from __future__ import annotations

import mimetypes
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .platform_db import PlatformDatabase
from .platform_paths import PlatformPaths


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_name(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("._")
    return stem[:160] or "attachment"


@dataclass(frozen=True)
class AttachmentRecord:
    attachment_id: str
    conversation_id: str
    original_name: str
    path: Path
    content_type: str
    size_bytes: int
    created_at: str


class AttachmentStore:
    def __init__(
        self,
        database: PlatformDatabase | None = None,
        root: Path | None = None,
        *,
        max_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        self.database = database or PlatformDatabase()
        self.root = Path(root or (PlatformPaths.default().data / "attachments"))
        self.max_bytes = int(max_bytes)
        if self.max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.root.mkdir(parents=True, exist_ok=True)

    def import_file(self, source: Path, *, conversation_id: str) -> AttachmentRecord:
        path = Path(source).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        size = path.stat().st_size
        if size > self.max_bytes:
            raise ValueError(f"Attachment is too large: {path.name}")
        attachment_id = uuid4().hex
        directory = self.root / str(conversation_id)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{attachment_id}-{_safe_name(path.name)}"
        shutil.copy2(path, destination)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        created = _now()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO attachments VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    attachment_id,
                    str(conversation_id),
                    path.name,
                    str(destination),
                    content_type,
                    size,
                    created,
                ),
            )
            connection.commit()
        return self.get(attachment_id)

    def get(self, attachment_id: str) -> AttachmentRecord:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM attachments WHERE attachment_id=?", (str(attachment_id),)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown attachment: {attachment_id}")
        return self._from_row(row)

    def list(self, conversation_id: str) -> tuple[AttachmentRecord, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM attachments WHERE conversation_id=? ORDER BY created_at",
                (str(conversation_id),),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def delete(self, attachment_id: str) -> bool:
        try:
            record = self.get(attachment_id)
        except KeyError:
            return False
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM attachments WHERE attachment_id=?", (attachment_id,)
            )
            connection.commit()
        record.path.unlink(missing_ok=True)
        return cursor.rowcount > 0

    @staticmethod
    def _from_row(row) -> AttachmentRecord:
        return AttachmentRecord(
            attachment_id=str(row["attachment_id"]),
            conversation_id=str(row["conversation_id"]),
            original_name=str(row["original_name"]),
            path=Path(str(row["stored_path"])),
            content_type=str(row["content_type"]),
            size_bytes=int(row["size_bytes"]),
            created_at=str(row["created_at"]),
        )
