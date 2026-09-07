"""One plain-language front door for every ChatMPD capability."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping

from .assistant import DesktopAssistant
from .router import RequestRouter, RouteDecision


SpecialistHandler = Callable[[str], Any]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


@dataclass(frozen=True)
class CommandResult:
    capability: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "message": self.message,
            "details": _jsonable(self.details),
        }


class ChatMPDOrchestrator:
    """Route a natural-language request to chat, coding, or a specialist."""

    def __init__(
        self,
        *,
        assistant: DesktopAssistant,
        router: RequestRouter | None = None,
        specialist_handlers: Mapping[str, SpecialistHandler] | None = None,
        platform_services: Any | None = None,
        intent_planner: Any | None = None,
        confidence_threshold: float = 0.55,
    ) -> None:
        self.assistant = assistant
        self.router = router or RequestRouter()
        self.specialist_handlers = dict(specialist_handlers or {})
        self.platform_services = platform_services
        self.intent_planner = intent_planner
        self.confidence_threshold = float(confidence_threshold)
        self._closed = False
        self._lock = RLock()

    def command(self, text: str, workspace: str | Path | None = None) -> CommandResult:
        with self._lock:
            return self._command_unlocked(text, workspace)

    def _command_unlocked(
        self, text: str, workspace: str | Path | None = None
    ) -> CommandResult:
        if self._closed:
            raise RuntimeError("ChatMPD is closed.")
        if self.platform_services is not None:
            capture = getattr(self.platform_services, "capture_explicit_memory", None)
            if callable(capture):
                capture(text)
        decision = self._decide_route(text, workspace)
        if decision.capability == "chat":
            turn = self.assistant.chat(text)
            tools_used = [str(item) for item in getattr(turn, "tools_used", ())]
            details = {"tools_used": tools_used} if tools_used else {}
            details.setdefault("status", "completed")
            details.setdefault("status_label", "Finishing up")
            return CommandResult("chat", str(turn.assistant), details)
        if decision.capability == "coding":
            if workspace is None or not str(workspace).strip():
                return CommandResult(
                    "coding",
                    "Choose a project folder so ChatMPD can edit and verify the code safely.",
                    {
                        "status": "needs_context",
                        "status_label": "Checking project",
                        "needs_context": {
                            "kind": "workspace",
                            "message": "A project folder is required for coding work.",
                        },
                        "suggested_action": "choose_workspace",
                    },
                )
            outcome = self.assistant.run_task(Path(workspace), text)
            result = outcome.result
            details = {
                "status": result.status,
                "status_label": "Verifying changes",
                "changed_files": list(result.changed_files),
                "checks": [
                    {"argv": list(check.argv), "exit_code": check.exit_code}
                    for check in result.checks
                ],
                "state_file": result.state_file,
                "models": list(getattr(outcome, "models", ())),
            }
            return CommandResult("coding", str(result.summary), details)

        handler = self.specialist_handlers.get(decision.capability)
        if handler is None:
            raise RuntimeError(
                f"ChatMPD capability is not configured: {decision.capability}"
            )
        release = getattr(self.assistant, "release_runtime", None)
        if callable(release):
            release()
        return self._normalize(decision.capability, handler(text))

    def _decide_route(
        self, text: str, workspace: str | Path | None
    ) -> RouteDecision:
        if self.intent_planner is not None:
            try:
                plan = self.intent_planner.plan(
                    text,
                    workspace=None if workspace is None else str(workspace),
                    capabilities=self._planner_capabilities(),
                )
                confidence = float(getattr(plan, "confidence", 0.0))
                if confidence < self.confidence_threshold:
                    raise ValueError("planner confidence below threshold")
                if hasattr(plan, "to_route_decision"):
                    return plan.to_route_decision()
                return RouteDecision(
                    capability=str(getattr(plan, "capability")),
                    requires_workspace=bool(getattr(plan, "requires_workspace", False)),
                    reason=str(getattr(plan, "reason", "")),
                )
            except Exception:
                pass
        return self.router.classify(text)

    def _planner_capabilities(self) -> tuple[str, ...]:
        routes = ["chat", "coding", *self.specialist_handlers.keys()]
        return tuple(dict.fromkeys(str(item) for item in routes if str(item).strip()))

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.assistant.close()
            closer = getattr(self.platform_services, "close", None)
            if callable(closer):
                closer()

    @staticmethod
    def _normalize(capability: str, value: Any) -> CommandResult:
        if isinstance(value, CommandResult):
            return value
        if isinstance(value, Mapping):
            details = dict(value)
            message = str(
                details.get("summary")
                or details.get("message")
                or details.get("status")
                or json.dumps(_jsonable(details), ensure_ascii=False)
            )
            details.setdefault("status", str(details.get("status") or "completed"))
            if capability == "media":
                details.setdefault("status_label", "Creating media")
            else:
                details.setdefault("status_label", "Working locally")
            return CommandResult(capability, message, details)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            details = dataclasses.asdict(value)
            message = str(details.get("summary") or details.get("status") or capability)
            details.setdefault("status", "completed")
            details.setdefault("status_label", "Working locally")
            return CommandResult(capability, message, details)
        return CommandResult(
            capability,
            str(value),
            {"status": "completed", "status_label": "Working locally"},
        )
