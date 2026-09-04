"""Persistent permission profiles layered over ChatMPD's critical-action gate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from .host_policy import HostAction, HostActionPolicy, HostDecision
from .platform_db import PlatformDatabase


@dataclass(frozen=True)
class PermissionProfile:
    name: str
    confirmation_categories: tuple[str, ...]


class PermissionProfileStore:
    def __init__(self, database: PlatformDatabase | None = None) -> None:
        self.database = database or PlatformDatabase()
        self._base = HostActionPolicy()

    def active_name(self) -> str:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? AND record_id=?",
                ("permission", "active"),
            ).fetchone()
        return "autonomous" if row is None else str(json.loads(row["payload"])["name"])

    def save_custom(
        self,
        name: str,
        *,
        confirmation_categories: Iterable[str],
    ) -> PermissionProfile:
        clean_name = "-".join(str(name).strip().casefold().split())
        if not clean_name or clean_name in {"safe", "autonomous"}:
            raise ValueError("Custom permission profile needs a distinct name.")
        categories = tuple(sorted({str(item).strip().casefold() for item in confirmation_categories if str(item).strip()}))
        profile = PermissionProfile(clean_name, categories)
        payload = json.dumps({"name": profile.name, "confirmation_categories": list(categories)})
        self._put(f"profile:{clean_name}", payload)
        return profile

    def set_active(self, name: str) -> str:
        clean = str(name).strip().casefold()
        if clean not in {"safe", "autonomous"}:
            self.get(clean)
        self._put("active", json.dumps({"name": clean}))
        return clean

    def get(self, name: str) -> PermissionProfile:
        clean = str(name).strip().casefold()
        if clean == "autonomous":
            return PermissionProfile("autonomous", ())
        if clean == "safe":
            return PermissionProfile("safe", ("files", "network", "desktop", "system", "plugins"))
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? AND record_id=?",
                ("permission", f"profile:{clean}"),
            ).fetchone()
        if row is None:
            raise KeyError(f"Unknown permission profile: {name}")
        data = json.loads(str(row["payload"]))
        return PermissionProfile(str(data["name"]), tuple(data.get("confirmation_categories") or ()))

    def evaluate(self, action: HostAction) -> HostDecision:
        base = self._base.evaluate(action)
        if base.requires_confirmation:
            return base
        profile = self.get(self.active_name())
        category = action.category.strip().casefold()
        if category in profile.confirmation_categories:
            return HostDecision(
                "profile-confirmation",
                True,
                f"Active profile '{profile.name}' requires confirmation for {category} actions.",
            )
        return base

    def _put(self, record_id: str, payload: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO platform_records(namespace, record_id, payload, updated_at) VALUES (?, ?, ?, ?)",
                ("permission", record_id, payload, now),
            )
            connection.commit()
