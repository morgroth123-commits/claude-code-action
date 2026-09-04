"""Unified inventory for ChatMPD built-ins and extensions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Callable


CapabilityHandler = Callable[..., Any]


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    title: str
    description: str = ""
    kind: str = "builtin"
    version: str = "1"
    enabled: bool = True
    risk: str = "safe"
    permissions: tuple[str, ...] = ()
    health: str = "ready"
    source: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class CapabilityRegistry:
    """Thread-safe capability catalog with optional invocation handlers."""

    def __init__(self) -> None:
        self._items: dict[str, CapabilityDescriptor] = {}
        self._handlers: dict[str, CapabilityHandler] = {}
        self._lock = RLock()

    def register(
        self,
        descriptor: CapabilityDescriptor,
        handler: CapabilityHandler | None = None,
    ) -> None:
        capability_id = descriptor.capability_id.strip()
        if not capability_id:
            raise ValueError("Capability id cannot be blank.")
        with self._lock:
            if capability_id in self._items:
                raise ValueError(f"Capability already registered: {capability_id}")
            self._items[capability_id] = descriptor
            if handler is not None:
                self._handlers[capability_id] = handler

    def replace(
        self,
        descriptor: CapabilityDescriptor,
        handler: CapabilityHandler | None = None,
    ) -> None:
        with self._lock:
            self._items[descriptor.capability_id] = descriptor
            if handler is None:
                self._handlers.pop(descriptor.capability_id, None)
            else:
                self._handlers[descriptor.capability_id] = handler

    def get(self, capability_id: str) -> CapabilityDescriptor:
        with self._lock:
            try:
                return self._items[capability_id]
            except KeyError as error:
                raise KeyError(f"Unknown capability: {capability_id}") from error

    def list(self, *, enabled_only: bool = False) -> tuple[CapabilityDescriptor, ...]:
        with self._lock:
            items = tuple(self._items.values())
        if enabled_only:
            items = tuple(item for item in items if item.enabled)
        return tuple(sorted(items, key=lambda item: (item.kind, item.title.casefold(), item.capability_id)))

    def search(self, query: str) -> tuple[CapabilityDescriptor, ...]:
        needle = str(query).strip().casefold()
        if not needle:
            return self.list()
        matches = []
        for item in self.list():
            haystack = " ".join((item.capability_id, item.title, item.description, item.kind)).casefold()
            if needle in haystack:
                matches.append(item)
        return tuple(matches)

    def invoke(self, capability_id: str, *args: Any, **kwargs: Any) -> Any:
        descriptor = self.get(capability_id)
        if not descriptor.enabled:
            raise RuntimeError(f"Capability is disabled: {capability_id}")
        if descriptor.health != "ready":
            raise RuntimeError(f"Capability is not ready: {capability_id} ({descriptor.health})")
        with self._lock:
            handler = self._handlers.get(capability_id)
        if handler is None:
            raise RuntimeError(f"Capability has no invocation handler: {capability_id}")
        return handler(*args, **kwargs)
