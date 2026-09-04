"""Translate local llama.cpp chat responses into deterministic engine turns."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from .doctrine import coding_agent_prompt
from .llamacpp import ChatResponse, ProviderError, ToolCall


TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List a bounded inventory of safe project files.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative directory, normally '.'.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read one UTF-8 text file inside the project workspace.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path"],
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative file path.",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Atomically create or replace one UTF-8 project file.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["path", "content"],
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative file path.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete new contents of the file.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search safe project text files with bounded results.",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string", "default": "."},
                    "case_sensitive": {"type": "boolean", "default": False},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_text",
            "description": "Atomically replace an exact text fragment in one safe project file.",
            "parameters": {
                "type": "object", "additionalProperties": False,
                "required": ["path", "old_text", "new_text"],
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "expected_replacements": {"type": "integer", "minimum": 1, "default": 1},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run one pre-approved command without a command shell.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": ["argv"],
                "properties": {
                    "argv": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "description": "An exact argv from the approved command list.",
                    }
                },
            },
        },
    },
]


class LocalCodingModel:
    """A stateful adapter from local chat completions to one engine action at a time."""

    def __init__(
        self,
        provider: Any,
        *,
        allowed_commands: list[list[str]],
        project_context: str = "",
    ) -> None:
        self.provider = provider
        self.allowed_commands = [list(command) for command in allowed_commands]
        self.project_context = project_context.strip()
        self._messages: list[dict[str, Any]] = []
        self._planned = False
        self._event_cursor = 0
        self._pending_call: ToolCall | None = None
        self._fallback_call_number = 0

    def next_turn(self, context: dict[str, Any]) -> dict[str, Any]:
        task = str(context.get("task", "")).strip()
        events = context.get("events", [])
        if not isinstance(events, list):
            raise RuntimeError("Agent context contains invalid events")

        if not self._planned:
            self._messages = [
                {"role": "system", "content": self._system_prompt()},
                {
                    "role": "user",
                    "content": self._initial_request(task),
                },
            ]
            response = self.provider.chat(deepcopy(self._messages))
            self._messages.append(
                {"role": "assistant", "content": response.text.strip()}
            )
            self._messages.append(
                {
                    "role": "user",
                    "content": (
                        "Begin executing that plan now. Call exactly one provided tool "
                        "in this response; do not summarize or claim completion."
                    ),
                }
            )
            self._planned = True
            self._event_cursor = len(events)
            return {"kind": "plan", "steps": self._plan_steps(response.text)}

        self._append_engine_feedback(events)
        response: ChatResponse = self.provider.chat(
            deepcopy(self._messages),
            tools=deepcopy(TOOLS),
            tool_choice="auto",
        )
        self._event_cursor = len(events)
        tool_calls = response.tool_calls
        if not tool_calls:
            fallback_call = self._text_tool_call(response.text)
            if fallback_call is not None:
                tool_calls = (fallback_call,)
        if tool_calls:
            if len(tool_calls) != 1:
                raise ProviderError("The local model requested multiple tools at once")
            call = tool_calls[0]
            self._pending_call = call
            self._messages.append(self._assistant_tool_message(response, call))
            return {
                "kind": "tool",
                "name": call.name,
                "arguments": dict(call.arguments),
            }

        summary = response.text.strip()
        self._messages.append({"role": "assistant", "content": summary})
        if not summary:
            return {
                "kind": "final",
                "outcome": "failed",
                "summary": "The local model returned no action or explanation.",
            }
        final_match = re.match(
            r"^(SUCCESS|FAILED):\s*(.*)$",
            summary,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if final_match is None:
            return {
                "kind": "final",
                "outcome": "failed",
                "summary": summary,
            }
        outcome = "success" if final_match.group(1).casefold() == "success" else "failed"
        clean_summary = final_match.group(2).strip()
        if not clean_summary:
            clean_summary = "The local model returned an empty final summary."
            outcome = "failed"
        return {"kind": "final", "outcome": outcome, "summary": clean_summary}

    def _verification_observed(self, events: list[dict[str, Any]]) -> bool:
        if not self.allowed_commands:
            return True
        last_write = 0
        passing: dict[tuple[str, ...], int] = {}
        for index, event in enumerate(events, start=1):
            if event.get("type") != "tool_finished":
                continue
            data = event.get("data", {})
            result = data.get("result", {}) if isinstance(data, dict) else {}
            sequence = event.get("sequence", index)
            if not isinstance(sequence, int):
                sequence = index
            if data.get("tool") == "write_file":
                last_write = max(last_write, sequence)
                continue
            if data.get("tool") != "run_command" or not isinstance(result, dict):
                continue
            argv = result.get("argv")
            if result.get("exit_code") == 0 and isinstance(argv, list):
                passing[tuple(str(part) for part in argv)] = sequence
        return all(
            passing.get(tuple(command), 0) > last_write
            for command in self.allowed_commands
        )

    def _text_tool_call(self, text: str) -> ToolCall | None:
        stripped = text.strip()
        if not stripped or len(stripped.encode("utf-8")) > 65_536:
            return None
        fenced = re.fullmatch(
            r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL | re.IGNORECASE
        )
        tagged = re.fullmatch(
            r"<tool_call>\s*(\{.*\})\s*</tool_call>",
            stripped,
            flags=re.DOTALL | re.IGNORECASE,
        )
        candidate = (fenced or tagged).group(1) if (fenced or tagged) else stripped
        try:
            decoded = json.loads(
                candidate,
                parse_constant=lambda unused: (_ for _ in ()).throw(ValueError()),
            )
        except (json.JSONDecodeError, ValueError):
            repairs: list[str] = []
            if candidate.startswith("{{"):
                repairs.append(candidate[1:])
            if candidate.startswith("{{") and candidate.endswith("}}"):
                repairs.append(candidate[1:-1])
            decoded = None
            for repaired in repairs:
                try:
                    decoded = json.loads(
                        repaired,
                        parse_constant=lambda unused: (_ for _ in ()).throw(ValueError()),
                    )
                    break
                except (json.JSONDecodeError, ValueError):
                    continue
            if decoded is None:
                return None
        if not isinstance(decoded, dict) or set(decoded) != {"name", "arguments"}:
            return None
        name = decoded.get("name")
        arguments = decoded.get("arguments")
        allowed_names = {
            tool["function"]["name"]
            for tool in TOOLS
            if isinstance(tool.get("function"), dict)
        }
        if not isinstance(name, str) or name not in allowed_names:
            return None
        if not isinstance(arguments, dict):
            return None
        self._fallback_call_number += 1
        return ToolCall(
            f"chatmpd_text_call_{self._fallback_call_number}", name, arguments
        )

    def _system_prompt(self) -> str:
        return coding_agent_prompt(self.allowed_commands)

    def _initial_request(self, task: str) -> str:
        context = (
            f"\n\nRead-only project context:\n{self.project_context}"
            if self.project_context
            else ""
        )
        return (
            f"Task: {task}{context}\n\nFirst provide a short numbered plan only. "
            "Do not call a tool in this planning response."
        )

    @staticmethod
    def _plan_steps(text: str) -> list[str]:
        steps: list[str] = []
        for raw_line in text.splitlines():
            line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", raw_line).strip()
            if not line or line.casefold() in {"plan", "plan:"}:
                continue
            steps.append(line[:200])
            if len(steps) == 8:
                break
        return steps or [
            "Inspect the relevant project files",
            "Implement the smallest safe change",
            "Run the approved verification checks",
        ]

    @staticmethod
    def _assistant_tool_message(
        response: ChatResponse, call: ToolCall
    ) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": response.text,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=True),
                    },
                }
            ],
        }

    def _append_engine_feedback(self, events: list[dict[str, Any]]) -> None:
        new_events = events[self._event_cursor :]
        if self._pending_call is not None:
            result_event = next(
                (
                    event
                    for event in new_events
                    if event.get("type") in {"tool_finished", "tool_failed"}
                ),
                None,
            )
            if result_event is None:
                raise RuntimeError("The engine did not return a result for the last tool")
            content = json.dumps(
                result_event.get("data", {}),
                ensure_ascii=True,
                sort_keys=True,
            )
            self._messages.append(
                {
                    "role": "tool",
                    "tool_call_id": self._pending_call.id,
                    "content": content,
                }
            )
            self._pending_call = None
            if self._verification_observed(events):
                guidance = (
                    "All required checks have passed after the latest project changes. "
                    "If the task is complete, return `SUCCESS: ` followed by a concise "
                    "final summary now without calling another tool. If it cannot be "
                    "completed, return `FAILED: ` and the reason. Otherwise, call exactly "
                    "one provided tool."
                )
            else:
                guidance = (
                    "Continue executing the plan now. Call exactly one provided tool in "
                    "this response; do not summarize or claim completion. Use the latest "
                    "tool result to choose the next action."
                )
            self._messages.append({"role": "user", "content": guidance})

        rejection = next(
            (
                event
                for event in new_events
                if event.get("type") == "completion_rejected"
            ),
            None,
        )
        if rejection is not None:
            reason = rejection.get("data", {}).get(
                "reason", "Required verification is incomplete"
            )
            self._messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Completion was rejected: {reason}. Continue with the approved "
                        "tools and do not claim success until verification passes."
                    ),
                }
            )
