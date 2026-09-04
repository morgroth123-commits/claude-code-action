"""Disabled-by-default permission-gated desktop input adapter."""

from __future__ import annotations

from typing import Any, Protocol

from .host_policy import HostAction, HostActionPolicy


class DesktopBackend(Protocol):
    def click(self, x: int, y: int) -> None: ...
    def type_text(self, text: str) -> None: ...


class _PyAutoGuiBackend:
    def _module(self):
        try:
            import pyautogui
        except ImportError as error:
            raise RuntimeError("Desktop control requires the local pyautogui package.") from error
        return pyautogui

    def click(self, x: int, y: int) -> None:
        self._module().click(x=x, y=y)

    def type_text(self, text: str) -> None:
        self._module().write(text, interval=0.01)


class DesktopController:
    def __init__(
        self,
        *,
        policy: Any | None = None,
        backend: DesktopBackend | None = None,
        enabled: bool = False,
    ) -> None:
        self.policy = policy or HostActionPolicy()
        self.backend = backend or _PyAutoGuiBackend()
        self.enabled = bool(enabled)

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def click(self, x: int, y: int, *, confirmed: bool = False) -> None:
        self._guard("click", f"screen:{int(x)},{int(y)}", confirmed)
        if not -100000 <= int(x) <= 100000 or not -100000 <= int(y) <= 100000:
            raise ValueError("Desktop coordinates are out of bounds.")
        self.backend.click(int(x), int(y))

    def type_text(self, text: str, *, confirmed: bool = False) -> None:
        value = str(text)
        if not value or len(value) > 10000:
            raise ValueError("Desktop text must contain 1-10000 characters.")
        self._guard("type", "active-window", confirmed)
        self.backend.type_text(value)

    def _guard(self, operation: str, target: str, confirmed: bool) -> None:
        if not self.enabled:
            raise RuntimeError("Desktop control is disabled by default. Enable it explicitly first.")
        decision = self.policy.evaluate(HostAction("desktop", operation, target))
        if decision.requires_confirmation and not confirmed:
            raise PermissionError(decision.reason)
