from __future__ import annotations

from copy import deepcopy
from typing import Any


class ScriptedModel:
    """Deterministic model used by the offline demo and acceptance tests."""

    def __init__(self, turns: list[dict[str, Any]]) -> None:
        self._turns = deepcopy(turns)
        self._position = 0

    def next_turn(self, context: dict[str, Any]) -> dict[str, Any]:
        if self._position >= len(self._turns):
            raise RuntimeError("The scripted model ran out of turns")
        turn = self._turns[self._position]
        self._position += 1
        self._verify_expectations(turn.pop("expect", {}), context)
        return turn

    @staticmethod
    def _verify_expectations(
        expectations: dict[str, Any], context: dict[str, Any]
    ) -> None:
        if expectations.get("last_exit_code_nonzero"):
            if context.get("last_exit_code") in (None, 0):
                raise RuntimeError("Expected a failed command observation")
        if "last_exit_code" in expectations:
            if context.get("last_exit_code") != expectations["last_exit_code"]:
                last_result = next(
                    (
                        event.get("data", {}).get("result", {})
                        for event in reversed(context.get("events", []))
                        if event.get("type") == "tool_finished"
                    ),
                    {},
                )
                raise RuntimeError(
                    "The command observation did not match the script: "
                    f"expected {expectations['last_exit_code']}, "
                    f"received {context.get('last_exit_code')}; "
                    f"stderr={last_result.get('stderr', '')!r}"
                )
        if "last_tool_error_type" in expectations:
            error = context.get("last_tool_error") or {}
            if error.get("error_type") != expectations["last_tool_error_type"]:
                raise RuntimeError(
                    "The tool error observation did not match the script: "
                    f"expected {expectations['last_tool_error_type']!r}, "
                    f"received {error.get('error_type')!r}"
                )
