"""One plain-language front door for every ChatMPD capability."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Mapping

from .assistant import DesktopAssistant
from .router import RequestRouter


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
    ) -> None:
        self.assistant = assistant
        self.router = router or RequestRouter()
        self.specialist_handlers = dict(specialist_handlers or {})
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
        decision = self.router.classify(text)
        if decision.capability == "chat":
            turn = self.assistant.chat(text)
            return CommandResult("chat", str(turn.assistant), {})
        if decision.capability == "coding":
            if workspace is None or not str(workspace).strip():
                raise ValueError("This coding request needs a project folder.")
            outcome = self.assistant.run_task(Path(workspace), text)
            result = outcome.result
            details = {
                "status": result.status,
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

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self.assistant.close()

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
            return CommandResult(capability, message, details)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            details = dataclasses.asdict(value)
            message = str(details.get("summary") or details.get("status") or capability)
            return CommandResult(capability, message, details)
        return CommandResult(capability, str(value), {})
