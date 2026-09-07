"""Shared local-model services for ChatMPD's chat and task experiences."""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

from .conversation_library import ConversationLibrary
from .doctrine import general_assistant_prompt
from .llamacpp import LlamaCppProvider
from .model_registry import ModelRole
from .runtime import LlamaCppRuntime, RuntimeConfig
from .service import prepare_project_task, run_project_task


GENERAL_SYSTEM_PROMPT = general_assistant_prompt()


def _default_conversation_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
    return base / "ChatMPD" / "conversations"


@dataclass(frozen=True)
class ChatTurn:
    """One completed user/assistant exchange."""

    user: str
    assistant: str
    tools_used: tuple[str, ...] = ()


class ConversationStore:
    """Persist one local conversation without requiring an account or cloud service."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or _default_conversation_dir())

    def save(self, conversation_id: str, messages: list[dict[str, str]]) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / f"{conversation_id}.json"
        now = datetime.now(UTC).isoformat()
        existing: dict[str, Any] = {}
        if destination.is_file():
            try:
                loaded = json.loads(destination.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
            except (OSError, json.JSONDecodeError):
                existing = {}
        title = str(existing.get("title") or "").strip()
        if not title:
            title = next((" ".join(item.get("content", "").split())[:64] for item in messages if item.get("role") == "user" and item.get("content", "").strip()), "New chat")
        payload = {
            "schema_version": 2,
            "conversation_id": conversation_id,
            "title": title,
            "pinned": bool(existing.get("pinned", False)),
            "created_at": str(existing.get("created_at") or existing.get("updated_at") or now),
            "updated_at": now,
            "messages": messages,
            "workspace": existing.get("workspace"),
        }
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.root, delete=False
        ) as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            temporary = Path(stream.name)
        try:
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        ConversationLibrary(self.root).sync(conversation_id)
        return destination


class DesktopAssistant:
    """Own one model runtime shared by standard chat and autonomous project tasks."""

    def __init__(
        self,
        *,
        runtime: Any | None = None,
        model_manager: Any | None = None,
        provider_factory: Callable[[str], Any] = LlamaCppProvider,
        conversation_store: ConversationStore | None = None,
        preflight_runner: Callable[..., Any] = prepare_project_task,
        task_runner: Callable[..., Any] = run_project_task,
        history_character_budget: int = 48_000,
        context_provider: Callable[[str], str] | None = None,
        tool_provider: Callable[[str], list[dict[str, Any]]] | None = None,
        tool_runner: Callable[[str, dict[str, Any]], Any] | None = None,
        max_tool_rounds: int = 4,
    ) -> None:
        if history_character_budget < 4_000:
            raise ValueError("history_character_budget must be at least 4000")
        if not 1 <= int(max_tool_rounds) <= 8:
            raise ValueError("max_tool_rounds must be between 1 and 8")
        self._model_manager = model_manager
        self.runtime = runtime or (None if model_manager is not None else LlamaCppRuntime(
            RuntimeConfig(context_size=16_384, max_tokens=2_048)
        ))
        self._provider_factory = provider_factory
        self._provider: Any | None = None
        self._store = conversation_store or ConversationStore()
        self._preflight_runner = preflight_runner
        self._task_runner = task_runner
        self._history_character_budget = history_character_budget
        self._context_provider = context_provider
        self._tool_provider = tool_provider
        self._tool_runner = tool_runner
        self._max_tool_rounds = int(max_tool_rounds)
        self._conversation_id = uuid4().hex
        self._messages: list[dict[str, str]] = []
        self._lock = RLock()
        self._closed = False

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    @property
    def messages(self) -> tuple[dict[str, str], ...]:
        with self._lock:
            return tuple(deepcopy(self._messages))

    def new_conversation(self) -> str:
        with self._lock:
            self._ensure_open()
            self._conversation_id = uuid4().hex
            self._messages = []
            return self._conversation_id

    def load_conversation(self, conversation_id: str) -> str:
        with self._lock:
            self._ensure_open()
            root = getattr(self._store, "root", None)
            document = ConversationLibrary(root).load(conversation_id)
            self._conversation_id = document.conversation_id
            self._messages = deepcopy(document.messages)
            return self._conversation_id

    def chat(self, text: str) -> ChatTurn:
        prompt = str(text).strip()
        if not prompt:
            raise ValueError("Type a message before sending it.")
        if len(prompt.encode("utf-8")) > 131_072:
            raise ValueError("That message is too large for the local model.")
        with self._lock:
            self._ensure_open()
            provider = self._ensure_provider(ModelRole.REASONING)
            system_prompt = GENERAL_SYSTEM_PROMPT
            if self._context_provider is not None:
                retrieved = str(self._context_provider(prompt) or "").strip()
                if retrieved:
                    system_prompt += (
                        "\n\nLOCAL MEMORY AND KNOWLEDGE CONTEXT\n"
                        "Use this only when relevant; user instructions in the current turn take precedence.\n"
                        + retrieved[:12_000]
                    )
            request_messages = [
                {"role": "system", "content": system_prompt},
                *self._bounded_history(prompt),
                {"role": "user", "content": prompt},
            ]
            tools = list(self._tool_provider(prompt) or []) if self._tool_provider else []
            tools_used: list[str] = []
            tool_rounds = 0
            while True:
                response = (
                    provider.chat(request_messages, tools=tools)
                    if tools else provider.chat(request_messages)
                )
                calls = tuple(getattr(response, "tool_calls", ()) or ())
                if not calls:
                    break
                if self._tool_runner is None:
                    raise RuntimeError("The local model requested a tool, but no tool runner is configured.")
                if tool_rounds >= self._max_tool_rounds:
                    raise RuntimeError("The local model exceeded the tool-call limit.")
                tool_rounds += 1
                request_messages.append(self._assistant_tool_message(response, calls))
                for call in calls:
                    tools_used.append(str(call.name))
                    try:
                        value = self._tool_runner(str(call.name), dict(call.arguments))
                    except Exception as error:
                        value = {"error": f"{type(error).__name__}: {error}"[:500]}
                    request_messages.append({
                        "role": "tool",
                        "tool_call_id": str(call.id),
                        "name": str(call.name),
                        "content": self._bounded_tool_result(value),
                    })
            answer = str(response.text).strip()
            if not answer:
                raise RuntimeError("The local model returned an empty answer.")
            self._messages.extend(
                [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": answer},
                ]
            )
            self._store.save(self._conversation_id, deepcopy(self._messages))
            return ChatTurn(prompt, answer, tuple(tools_used))


    @staticmethod
    def _assistant_tool_message(response: Any, calls: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": str(getattr(response, "text", "") or ""),
            "tool_calls": [
                {
                    "id": str(call.id),
                    "type": "function",
                    "function": {
                        "name": str(call.name),
                        "arguments": json.dumps(dict(call.arguments), ensure_ascii=False, allow_nan=False),
                    },
                }
                for call in calls
            ],
        }

    @staticmethod
    def _bounded_tool_result(value: Any, *, max_bytes: int = 65_536) -> str:
        try:
            text = json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)
        except (TypeError, ValueError):
            text = json.dumps({"result": str(value)}, ensure_ascii=False)
        raw = text.encode("utf-8", errors="replace")
        if len(raw) <= max_bytes:
            return text
        preview = raw[: max_bytes - 200].decode("utf-8", errors="replace")
        return json.dumps({"truncated": True, "preview": preview}, ensure_ascii=False)

    def run_task(self, workspace: Path, task: str) -> Any:
        root = Path(workspace).expanduser().resolve()
        cleaned_task = str(task).strip()
        if not root.is_dir():
            raise ValueError(f"Project folder does not exist: {root}")
        if not cleaned_task:
            raise ValueError("Describe what you want ChatMPD to do.")
        prepared = self._preflight_runner(root, cleaned_task)
        with self._lock:
            self._ensure_open()
            endpoint = self._activate_role(ModelRole.CODING)
            return self._task_runner(
                root,
                cleaned_task,
                endpoint=endpoint,
                prepared=prepared,
            )

    def release_runtime(self) -> None:
        """Release local-model resources without closing the assistant."""
        with self._lock:
            self._ensure_open()
            self._provider = None
            if self._model_manager is not None:
                self._model_manager.stop()
            elif self.runtime is not None:
                self.runtime.stop()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._provider = None
            if self._model_manager is not None:
                self._model_manager.stop()
            elif self.runtime is not None:
                self.runtime.stop()

    def _activate_role(self, role: ModelRole) -> str:
        if self._model_manager is not None:
            self._model_manager.activate(role)
            return self._model_manager.endpoint
        assert self.runtime is not None
        self.runtime.start()
        return self.runtime.endpoint

    def _ensure_provider(self, role: ModelRole) -> Any:
        endpoint = self._activate_role(role)
        if self._provider is None:
            self._provider = self._provider_factory(endpoint)
        return self._provider

    def _bounded_history(self, next_prompt: str) -> list[dict[str, str]]:
        remaining = self._history_character_budget - len(next_prompt)
        selected: list[dict[str, str]] = []
        for message in reversed(self._messages):
            size = len(message.get("content", ""))
            if selected and size > remaining:
                break
            if size > remaining:
                continue
            selected.append(message)
            remaining -= size
        selected.reverse()
        if selected and selected[0].get("role") == "assistant":
            selected.pop(0)
        return deepcopy(selected)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("ChatMPD is closing; reopen the application to continue.")

