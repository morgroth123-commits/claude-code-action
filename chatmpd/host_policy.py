"""Central autonomy gate for host-level ChatMPD actions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HostAction:
    category: str
    operation: str
    target: str


@dataclass(frozen=True)
class HostDecision:
    level: str
    requires_confirmation: bool
    reason: str


class HostActionPolicy:
    """Allow ordinary reversible work; escalate critical system boundaries."""

    _CRITICAL_CATEGORIES = {
        "credentials",
        "disk",
        "firmware",
        "security",
        "boot",
        "account",
        "permission",
    }

    _DESTRUCTIVE_OPERATIONS = {
        "format",
        "partition",
        "erase",
        "wipe",
        "disable",
        "delete",
        "export",
    }
    _CRITICAL_TARGET_FRAGMENTS = (
        r"c:\windows\system32",
        r"c:\windows\boot",
        "uefi",
        "bios",
        "bitlocker",
        "windows defender",
        "browser passwords",
    )

    def evaluate(self, action: HostAction) -> HostDecision:
        category = action.category.strip().casefold()
        operation = action.operation.strip().casefold()
        target = action.target.strip().casefold()
        critical = category in self._CRITICAL_CATEGORIES
        critical = critical or operation in self._DESTRUCTIVE_OPERATIONS and any(
            marker in target for marker in self._CRITICAL_TARGET_FRAGMENTS
        )
        if critical:
            return HostDecision(
                "critical",
                True,
                "Action crosses a critical system boundary and needs explicit approval.",
            )
        return HostDecision(
            "autonomous",
            False,
            "Ordinary reversible host work may proceed autonomously.",
        )
