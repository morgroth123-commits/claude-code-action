"""Permission-aware bridge from local extensions to ordinary ChatMPD chat."""

from __future__ import annotations

import json
import re
from pathlib import Path
from threading import RLock
from typing import Any

from .activity import ActivityLog
from .capabilities import CapabilityDescriptor
from .extensions import ExtensionManager
from .external_tools import ExternalToolRunner
from .host_policy import HostAction
from .permissions import PermissionProfileStore


_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]{2,}", re.I)


class AssistantCapabilityBroker:
    """Offer only relevant, ready extensions that can run without new approval."""

    def __init__(
        self,
        *,
        extensions: ExtensionManager,
        permissions: PermissionProfileStore,
        activity: ActivityLog,
        runner: ExternalToolRunner | None = None,
        max_tools: int = 8,
    ) -> None:
        self.extensions = extensions
        self.permissions = permissions
        self.activity = activity
        self.runner = runner or ExternalToolRunner()
        self.max_tools = max(1, min(int(max_tools), 16))
        self._offered: dict[str, CapabilityDescriptor] = {}
        self._lock = RLock()

    def skill_context(self, prompt: str, *, max_skills: int = 3, max_chars: int = 6000) -> str:
        ranked = self._ranked(prompt, kind="skill")[: max(1, min(int(max_skills), 8))]
        sections: list[str] = []
        used = 0
        for _score, descriptor in ranked:
            if not self._eligible(descriptor):
                continue
            try:
                body = self.extensions.skill_text(descriptor.capability_id).strip()
            except (OSError, KeyError):
                continue
            remaining = max_chars - used
            if remaining <= 0:
                break
            section = f"SKILL: {descriptor.title}\n{body}"[:remaining]
            sections.append(section)
            used += len(section)
        return "\n\n".join(sections)

    def tools_for_prompt(self, prompt: str) -> list[dict[str, Any]]:
        offered: dict[str, CapabilityDescriptor] = {}
        tools: list[dict[str, Any]] = []
        for _score, descriptor in self._ranked(prompt):
            if descriptor.kind == "skill" or not self._eligible(descriptor):
                continue
            name = self._tool_name(descriptor.capability_id)
            if name in offered:
                continue
            parameters = descriptor.metadata.get("parameters")
            if not isinstance(parameters, dict):
                parameters = {
                    "type": "object",
                    "properties": {
                        "input": {
                            "type": "string",
                            "description": "Natural-language input for this capability.",
                        }
                    },
                }
            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": descriptor.description or descriptor.title,
                    "parameters": parameters,
                },
            })
            offered[name] = descriptor
            if len(tools) >= self.max_tools:
                break
        with self._lock:
            self._offered = offered
        return tools

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        with self._lock:
            descriptor = self._offered.get(str(tool_name))
        if descriptor is None:
            raise KeyError(f"Tool was not offered for this request: {tool_name}")
        if not self._eligible(descriptor):
            raise PermissionError(f"Capability is no longer eligible: {descriptor.title}")
        try:
            result = self._invoke_descriptor(descriptor, dict(arguments))
        except Exception as error:
            self.activity.record(
                "tool",
                f"Extension tool failed: {descriptor.title}",
                details={"capability": descriptor.capability_id, "error": type(error).__name__},
            )
            raise
        self.activity.record(
            "tool",
            f"Extension tool completed: {descriptor.title}",
            details={"capability": descriptor.capability_id},
        )
        return result

    def _invoke_descriptor(self, descriptor: CapabilityDescriptor, arguments: dict[str, Any]) -> Any:
        source = descriptor.source or Path()
        entrypoint = str(descriptor.metadata.get("entrypoint") or "").strip()
        if descriptor.kind == "plugin":
            if not entrypoint:
                raise RuntimeError("Plugin extension has no entrypoint.")
            return self.runner.run_plugin(source / entrypoint, arguments)
        if descriptor.kind == "cli":
            command = descriptor.metadata.get("command")
            if not isinstance(command, list) or not command:
                raise RuntimeError("CLI extension command must be an argv array.")
            argv = [str(item) for item in command]
            if descriptor.source and argv:
                first = Path(argv[0])
                if not first.is_absolute() and (source / first).exists():
                    argv[0] = str((source / first).resolve())
            result = self.runner.run_cli(
                argv, input_text=json.dumps(arguments, ensure_ascii=False, allow_nan=False)
            )
            if result.exit_code != 0:
                raise RuntimeError(f"CLI extension failed with exit code {result.exit_code}.")
            try:
                value = json.loads(result.stdout or "{}")
            except json.JSONDecodeError:
                return {"stdout": result.stdout[:8192]}
            return value
        if descriptor.kind == "http":
            endpoint = str(descriptor.metadata.get("endpoint") or "").strip()
            if not endpoint:
                raise RuntimeError("HTTP extension has no endpoint.")
            return self.runner.run_http(endpoint, arguments, allow_network=True)
        if descriptor.kind == "mcp":
            return self._invoke_mcp(descriptor, arguments)
        raise RuntimeError(f"Unsupported automatic extension kind: {descriptor.kind}")

    def _invoke_mcp(self, descriptor: CapabilityDescriptor, arguments: dict[str, Any]) -> Any:
        tool_name = str(descriptor.metadata.get("tool_name") or "").strip()
        if not tool_name:
            raise RuntimeError("MCP extension requires extension.tool_name.")
        endpoint = str(descriptor.metadata.get("endpoint") or "").strip()
        if endpoint:
            return self.runner.call_mcp_http(endpoint, tool_name, arguments)
        command = descriptor.metadata.get("command")
        if not isinstance(command, list) or not command:
            raise RuntimeError("MCP extension requires an endpoint or argv command.")
        return self.runner.call_mcp([str(item) for item in command], tool_name, arguments)

    def _eligible(self, descriptor: CapabilityDescriptor) -> bool:
        if not descriptor.enabled or descriptor.health != "ready" or descriptor.risk == "critical":
            return False
        permissions = set(descriptor.permissions)
        if descriptor.kind in {"http", "mcp"} and descriptor.metadata.get("endpoint"):
            if "network" not in permissions:
                return False
        for category in permissions:
            decision = self.permissions.evaluate(
                HostAction(str(category), "invoke", descriptor.title)
            )
            if decision.requires_confirmation:
                return False
        return True

    def _ranked(
        self, prompt: str, *, kind: str | None = None
    ) -> list[tuple[int, CapabilityDescriptor]]:
        prompt_tokens = {item.casefold() for item in _TOKEN.findall(str(prompt))}
        ranked: list[tuple[int, CapabilityDescriptor]] = []
        for descriptor in self.extensions.discover():
            if kind is not None and descriptor.kind != kind:
                continue
            tags = descriptor.metadata.get("tags") or []
            haystack = " ".join(
                [descriptor.capability_id, descriptor.title, descriptor.description,
                 *(str(item) for item in tags)]
            )
            descriptor_tokens = {item.casefold() for item in _TOKEN.findall(haystack)}
            score = len(prompt_tokens.intersection(descriptor_tokens))
            if score:
                ranked.append((score, descriptor))
        ranked.sort(key=lambda item: (-item[0], item[1].title.casefold()))
        return ranked

    @staticmethod
    def _tool_name(capability_id: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(capability_id)).strip("_")
        if not cleaned:
            cleaned = "extension"
        if cleaned[0].isdigit():
            cleaned = "x_" + cleaned
        return ("ext_" + cleaned)[:64]
