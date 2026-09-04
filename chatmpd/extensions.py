"""Manifest-based discovery for ChatMPD skills and plugins."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from .capabilities import CapabilityDescriptor, CapabilityRegistry
from .platform_paths import PlatformPaths


_ALLOWED_KINDS = {"skill", "plugin", "cli", "http", "mcp"}
_ALLOWED_RISKS = {"safe", "autonomous", "critical"}


class ExtensionManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or PlatformPaths.default().extensions)

    def discover(self) -> tuple[CapabilityDescriptor, ...]:
        if not self.root.is_dir():
            return ()
        items: list[CapabilityDescriptor] = []
        for manifest in sorted(self.root.glob("*/skill.toml")):
            try:
                items.append(self._load_manifest(manifest))
            except Exception as error:
                items.append(self._broken_descriptor(manifest, error))
        return tuple(items)

    def populate(self, registry: CapabilityRegistry) -> None:
        for item in self.discover():
            registry.register(item)

    def skill_text(self, capability_id: str) -> str:
        descriptor = next(
            (item for item in self.discover() if item.capability_id == capability_id), None
        )
        if descriptor is None or descriptor.kind != "skill" or descriptor.source is None:
            raise KeyError(f"Unknown skill: {capability_id}")
        entrypoint = str(descriptor.metadata.get("entrypoint") or "SKILL.md")
        path = descriptor.source / entrypoint
        return path.read_text(encoding="utf-8")

    def _load_manifest(self, path: Path) -> CapabilityDescriptor:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
        raw = payload.get("extension")
        if not isinstance(raw, dict):
            raise ValueError("Manifest requires an [extension] table.")
        capability_id = self._required_text(raw, "id")
        title = self._required_text(raw, "name")
        kind = str(raw.get("kind") or "skill").strip().casefold()
        if kind not in _ALLOWED_KINDS:
            raise ValueError(f"Unsupported extension kind: {kind}")
        risk = str(raw.get("risk") or "safe").strip().casefold()
        if risk not in _ALLOWED_RISKS:
            raise ValueError(f"Unsupported extension risk: {risk}")
        entrypoint = str(raw.get("entrypoint") or ("SKILL.md" if kind == "skill" else "")).strip()
        source = path.parent
        health = "ready"
        if entrypoint and not (source / entrypoint).is_file():
            health = "broken"
        permissions_value = raw.get("permissions") or []
        if not isinstance(permissions_value, list):
            raise ValueError("permissions must be an array of strings")
        permissions = tuple(str(item).strip() for item in permissions_value if str(item).strip())
        metadata: dict[str, Any] = {
            "entrypoint": entrypoint,
            "command": raw.get("command"),
            "endpoint": raw.get("endpoint"),
            "tags": raw.get("tags") or [],
        }
        return CapabilityDescriptor(
            capability_id=capability_id,
            title=title,
            description=str(raw.get("description") or "").strip(),
            kind=kind,
            version=str(raw.get("version") or "1").strip(),
            enabled=bool(raw.get("enabled", True)),
            risk=risk,
            permissions=permissions,
            health=health,
            source=source,
            metadata=metadata,
        )

    @staticmethod
    def _required_text(raw: dict[str, Any], name: str) -> str:
        value = str(raw.get(name) or "").strip()
        if not value:
            raise ValueError(f"Manifest requires extension.{name}.")
        return value

    @staticmethod
    def _broken_descriptor(path: Path, error: Exception) -> CapabilityDescriptor:
        fallback_id = f"broken.{path.parent.name}"
        try:
            payload = tomllib.loads(path.read_text(encoding="utf-8"))
            raw = payload.get("extension") if isinstance(payload, dict) else None
            if isinstance(raw, dict):
                fallback_id = str(raw.get("id") or fallback_id).strip() or fallback_id
                title = str(raw.get("name") or path.parent.name).strip() or path.parent.name
            else:
                title = path.parent.name
        except Exception:
            title = path.parent.name
        return CapabilityDescriptor(
            capability_id=fallback_id,
            title=title,
            description=f"Extension is unavailable: {type(error).__name__}: {error}",
            kind="skill",
            enabled=False,
            risk="safe",
            health="broken",
            source=path.parent,
            metadata={"manifest": str(path)},
        )
