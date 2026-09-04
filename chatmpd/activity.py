"""Visible evidence timeline for ChatMPD operations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import uuid4

from .platform_db import PlatformDatabase


@dataclass(frozen=True)
class ActivityEvent:
    event_id: str
    kind: str
    summary: str
    details: dict[str, Any]
    created_at: str


class ActivityLog:
    _FORBIDDEN_KINDS = {"reasoning", "chain_of_thought", "private_reasoning"}

    def __init__(self, database: PlatformDatabase | None = None) -> None:
        self.database = database or PlatformDatabase()

    def record(
        self,
        kind: str,
        summary: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> ActivityEvent:
        clean_kind = str(kind).strip().casefold()
        if clean_kind in self._FORBIDDEN_KINDS:
            raise ValueError("Activity log cannot store private reasoning.")
        clean_summary = " ".join(str(summary).split()).strip()
        if not clean_kind or not clean_summary:
            raise ValueError("Activity kind and summary are required.")
        event = ActivityEvent(
            uuid4().hex,
            clean_kind[:60],
            clean_summary[:1000],
            dict(details or {}),
            datetime.now(UTC).isoformat(),
        )
        payload = json.dumps(event.__dict__, ensure_ascii=False, default=str)
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO platform_records(namespace, record_id, payload, updated_at) VALUES (?, ?, ?, ?)",
                ("activity", event.event_id, payload, event.created_at),
            )
            connection.commit()
        return event

    def list(self, *, limit: int = 200) -> tuple[ActivityEvent, ...]:
        bounded = max(1, min(int(limit), 1000))
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? ORDER BY updated_at DESC LIMIT ?",
                ("activity", bounded),
            ).fetchall()
        events: list[ActivityEvent] = []
        for row in rows:
            data = json.loads(str(row["payload"]))
            events.append(ActivityEvent(
                event_id=str(data["event_id"]),
                kind=str(data["kind"]),
                summary=str(data["summary"]),
                details=dict(data.get("details") or {}),
                created_at=str(data["created_at"]),
            ))
        return tuple(events)
