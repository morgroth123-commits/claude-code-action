"""Durable, user-controlled long-term memory for ChatMPD."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from .platform_db import PlatformDatabase


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _query(text: str) -> str:
    words = re.findall(r"[\w-]+", str(text), flags=re.UNICODE)
    return " AND ".join(f'"{word}"' for word in words)


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    content: str
    kind: str
    source: str
    pinned: bool
    created_at: str
    updated_at: str


class MemoryStore:
    def __init__(self, database: PlatformDatabase | None = None) -> None:
        self.database = database or PlatformDatabase()

    def add(
        self,
        content: str,
        *,
        kind: str = "fact",
        source: str = "user",
        pinned: bool = False,
    ) -> MemoryRecord:
        text = str(content).strip()
        if not text:
            raise ValueError("Memory content cannot be blank.")
        now = _now()
        memory_id = uuid4().hex
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?)",
                (memory_id, text, str(kind), str(source), int(bool(pinned)), now, now),
            )
            connection.execute(
                "INSERT INTO memories_fts(memory_id, content, source) VALUES (?, ?, ?)",
                (memory_id, text, str(source)),
            )
            connection.commit()
        return self.get(memory_id)

    def get(self, memory_id: str) -> MemoryRecord:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE memory_id=?", (str(memory_id),)
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown memory: {memory_id}")
        return self._from_row(row)

    def update(
        self,
        memory_id: str,
        content: str,
        *,
        pinned: bool | None = None,
        kind: str | None = None,
    ) -> MemoryRecord:
        current = self.get(memory_id)
        text = str(content).strip()
        if not text:
            raise ValueError("Memory content cannot be blank.")
        next_pinned = current.pinned if pinned is None else bool(pinned)
        next_kind = current.kind if kind is None else str(kind).strip() or current.kind
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE memories SET content=?, kind=?, pinned=?, updated_at=? WHERE memory_id=?",
                (text, next_kind, int(next_pinned), _now(), memory_id),
            )
            connection.execute("DELETE FROM memories_fts WHERE memory_id=?", (memory_id,))
            connection.execute(
                "INSERT INTO memories_fts(memory_id, content, source) VALUES (?, ?, ?)",
                (memory_id, text, current.source),
            )
            connection.commit()
        return self.get(memory_id)

    def delete(self, memory_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute("DELETE FROM memories WHERE memory_id=?", (memory_id,))
            connection.execute("DELETE FROM memories_fts WHERE memory_id=?", (memory_id,))
            connection.commit()
            return cursor.rowcount > 0

    def list(self, *, limit: int = 200) -> tuple[MemoryRecord, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memories ORDER BY pinned DESC, updated_at DESC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def search(self, text: str, *, limit: int = 20) -> tuple[MemoryRecord, ...]:
        expression = _query(text)
        if not expression:
            return self.list(limit=limit)
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT m.* FROM memories_fts f
                JOIN memories m ON m.memory_id=f.memory_id
                WHERE memories_fts MATCH ?
                ORDER BY m.pinned DESC, bm25(memories_fts), m.updated_at DESC
                LIMIT ?
                """,
                (expression, max(1, min(int(limit), 200))),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    @staticmethod
    def _from_row(row) -> MemoryRecord:
        return MemoryRecord(
            memory_id=str(row["memory_id"]),
            content=str(row["content"]),
            kind=str(row["kind"]),
            source=str(row["source"]),
            pinned=bool(row["pinned"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
