"""Persistent local scheduler and conditional automation engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from .platform_db import PlatformDatabase


@dataclass(frozen=True)
class Automation:
    automation_id: str
    name: str
    command: str
    interval_seconds: int
    next_run: datetime
    condition_contains: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class AutomationRun:
    automation_id: str
    ran_at: datetime
    result: str
    condition_met: bool


class AutomationStore:
    def __init__(self, database: PlatformDatabase | None = None) -> None:
        self.database = database or PlatformDatabase()

    def create(
        self,
        name: str,
        command: str,
        *,
        interval_seconds: int,
        start_at: datetime | None = None,
        condition_contains: str | None = None,
    ) -> Automation:
        if int(interval_seconds) < 60:
            raise ValueError("interval_seconds must be at least 60")
        clean_name = " ".join(str(name).split()).strip()
        clean_command = str(command).strip()
        if not clean_name or not clean_command:
            raise ValueError("Automation name and command are required.")
        when = start_at or datetime.now(UTC)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        record = Automation(
            uuid4().hex,
            clean_name[:120],
            clean_command,
            int(interval_seconds),
            when.astimezone(UTC),
            None if condition_contains is None else str(condition_contains).strip() or None,
            True,
        )
        self._write(record)
        return record

    def get(self, automation_id: str) -> Automation:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? AND record_id=?",
                ("automation", str(automation_id)),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown automation: {automation_id}")
        return self._decode(str(row["payload"]))

    def list(self) -> tuple[Automation, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? ORDER BY updated_at DESC",
                ("automation",),
            ).fetchall()
        return tuple(self._decode(str(row["payload"])) for row in rows)

    def set_enabled(self, automation_id: str, enabled: bool) -> Automation:
        record = replace(self.get(automation_id), enabled=bool(enabled))
        self._write(record)
        return record

    def delete(self, automation_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM platform_records WHERE namespace=? AND record_id=?",
                ("automation", str(automation_id)),
            )
            connection.commit()
            return cursor.rowcount > 0

    def run_due(
        self,
        now: datetime,
        runner: Callable[[str], Any],
    ) -> tuple[AutomationRun, ...]:
        current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        current = current.astimezone(UTC)
        completed: list[AutomationRun] = []
        for record in self.list():
            if not record.enabled or record.next_run > current:
                continue
            result = str(runner(record.command))
            condition = record.condition_contains
            matched = True if not condition else condition.casefold() in result.casefold()
            completed.append(AutomationRun(record.automation_id, current, result, matched))
            next_run = record.next_run
            interval = timedelta(seconds=record.interval_seconds)
            while next_run <= current:
                next_run += interval
            self._write(replace(record, next_run=next_run))
        return tuple(completed)

    def _write(self, record: Automation) -> None:
        payload = json.dumps({
            "automation_id": record.automation_id,
            "name": record.name,
            "command": record.command,
            "interval_seconds": record.interval_seconds,
            "next_run": record.next_run.isoformat(),
            "condition_contains": record.condition_contains,
            "enabled": record.enabled,
        })
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO platform_records(namespace, record_id, payload, updated_at) VALUES (?, ?, ?, ?)",
                ("automation", record.automation_id, payload, datetime.now(UTC).isoformat()),
            )
            connection.commit()

    @staticmethod
    def _decode(payload: str) -> Automation:
        data = json.loads(payload)
        next_run = datetime.fromisoformat(str(data["next_run"]))
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=UTC)
        return Automation(
            automation_id=str(data["automation_id"]),
            name=str(data["name"]),
            command=str(data["command"]),
            interval_seconds=int(data["interval_seconds"]),
            next_run=next_run.astimezone(UTC),
            condition_contains=data.get("condition_contains"),
            enabled=bool(data.get("enabled", True)),
        )
