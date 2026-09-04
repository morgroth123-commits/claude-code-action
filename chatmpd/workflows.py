"""Persistent reusable ChatMPD workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .platform_db import PlatformDatabase


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    name: str
    command: str
    workspace: str | None
    created_at: str
    updated_at: str


class WorkflowStore:
    def __init__(self, database: PlatformDatabase | None = None) -> None:
        self.database = database or PlatformDatabase()

    def save(self, name: str, command: str, *, workspace: str | None = None) -> Workflow:
        clean_name = " ".join(str(name).split()).strip()
        clean_command = str(command).strip()
        if not clean_name or not clean_command:
            raise ValueError("Workflow name and command are required.")
        now = _now()
        workflow = Workflow(uuid4().hex, clean_name[:120], clean_command, workspace, now, now)
        self._write(workflow)
        return workflow

    def get(self, workflow_id: str) -> Workflow:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? AND record_id=?",
                ("workflow", str(workflow_id)),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown workflow: {workflow_id}")
        return self._decode(str(row["payload"]))

    def list(self) -> tuple[Workflow, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? ORDER BY updated_at DESC",
                ("workflow",),
            ).fetchall()
        return tuple(self._decode(str(row["payload"])) for row in rows)

    def delete(self, workflow_id: str) -> bool:
        with self.database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM platform_records WHERE namespace=? AND record_id=?",
                ("workflow", str(workflow_id)),
            )
            connection.commit()
            return cursor.rowcount > 0

    def replay(self, workflow_id: str, runner: Callable[..., Any]) -> Any:
        workflow = self.get(workflow_id)
        return runner(workflow.command, workspace=workflow.workspace)

    def _write(self, workflow: Workflow) -> None:
        payload = json.dumps(workflow.__dict__, ensure_ascii=False)
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO platform_records(namespace, record_id, payload, updated_at) VALUES (?, ?, ?, ?)",
                ("workflow", workflow.workflow_id, payload, workflow.updated_at),
            )
            connection.commit()

    @staticmethod
    def _decode(payload: str) -> Workflow:
        data = json.loads(payload)
        return Workflow(**data)
