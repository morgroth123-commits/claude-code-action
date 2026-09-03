"""A local-only, standard-library client for llama.cpp's OpenAI endpoint."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener


def _reject_non_standard_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


class ProviderError(RuntimeError):
    """A safe error raised when the local model provider cannot be used."""


@dataclass(frozen=True)
class ToolCall:
    """A native llama.cpp function call normalized for the agent runtime."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatResponse:
    """The assistant output from one non-streaming completion."""

    text: str
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str | None


class LlamaCppProvider:
    """Connect to a loopback-only llama.cpp server."""

    def __init__(
        self, endpoint: str = "http://127.0.0.1:8080", timeout: float = 10.0
    ) -> None:
        parsed = urlparse(endpoint)
        try:
            port = parsed.port
        except ValueError:
            raise ProviderError("llama.cpp endpoint must be a loopback HTTP URL") from None
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
            or port == 0
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise ProviderError("llama.cpp endpoint must be a loopback HTTP URL")
        if not 0 < timeout <= 600:
            raise ProviderError("llama.cpp timeout must be between 0 and 600 seconds")
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._opener = build_opener(ProxyHandler({}))

    def health(self) -> bool:
        """Return true only once the local server reports a ready model."""
        response = self._request("GET", "/health")
        if not isinstance(response, dict) or response.get("status") != "ok":
            raise ProviderError("llama.cpp returned an invalid health response")
        return True

    def models(self) -> tuple[str, ...]:
        """Return the model identifiers advertised by the local server."""
        response = self._request("GET", "/v1/models")
        if not isinstance(response, dict) or not isinstance(response.get("data"), list):
            raise ProviderError("llama.cpp returned an invalid models response")
        model_ids: list[str] = []
        for model in response["data"]:
            if not isinstance(model, dict) or not isinstance(model.get("id"), str):
                raise ProviderError("llama.cpp returned an invalid models response")
            model_id = model["id"].strip()
            if not model_id:
                raise ProviderError("llama.cpp returned an invalid models response")
            model_ids.append(model_id)
        return tuple(model_ids)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Request one non-streaming response using llama.cpp native tools."""
        self._validate_messages(messages)
        if tools is not None:
            self._validate_tools(tools)
        if tool_choice is not None and not isinstance(tool_choice, (str, dict)):
            raise ProviderError("llama.cpp tool choice has an invalid shape")

        payload: dict[str, Any] = {
            "messages": messages,
            "stream": False,
            "temperature": 0,
            "parallel_tool_calls": False,
        }
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        return self._normalize_chat_response(
            self._request("POST", "/v1/chat/completions", payload)
        )

    @staticmethod
    def _validate_messages(messages: object) -> None:
        if not isinstance(messages, list) or not messages:
            raise ProviderError("llama.cpp messages must be a non-empty list")
        for message in messages:
            if not isinstance(message, dict) or not isinstance(message.get("role"), str):
                raise ProviderError("llama.cpp message has an invalid shape")

    @staticmethod
    def _validate_tools(tools: object) -> None:
        if not isinstance(tools, list):
            raise ProviderError("llama.cpp tools must be a list")
        for tool in tools:
            function = tool.get("function") if isinstance(tool, dict) else None
            if (
                not isinstance(function, dict)
                or tool.get("type") != "function"
                or not isinstance(function.get("name"), str)
                or not function["name"].strip()
                or not isinstance(function.get("parameters"), dict)
            ):
                raise ProviderError("llama.cpp tool schema has an invalid shape")

    @classmethod
    def _normalize_chat_response(cls, response: object) -> ChatResponse:
        if not isinstance(response, dict) or not isinstance(response.get("choices"), list):
            raise ProviderError("llama.cpp returned an invalid chat response")
        choices = response["choices"]
        if len(choices) != 1 or not isinstance(choices[0], dict):
            raise ProviderError("llama.cpp returned an invalid chat response")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ProviderError("llama.cpp returned an invalid chat response")
        content = message.get("content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise ProviderError("llama.cpp returned an invalid chat response")
        raw_calls = message.get("tool_calls", [])
        if not isinstance(raw_calls, list):
            raise ProviderError("llama.cpp returned an invalid chat response")
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None and not isinstance(finish_reason, str):
            raise ProviderError("llama.cpp returned an invalid chat response")
        return ChatResponse(
            text=content,
            tool_calls=tuple(cls._normalize_tool_call(call) for call in raw_calls),
            finish_reason=finish_reason,
        )

    @staticmethod
    def _normalize_tool_call(raw_call: object) -> ToolCall:
        if not isinstance(raw_call, dict):
            raise ProviderError("llama.cpp returned an invalid tool call")
        function = raw_call.get("function")
        call_id = raw_call.get("id")
        if (
            not isinstance(function, dict)
            or not isinstance(call_id, str)
            or not call_id.strip()
            or not isinstance(function.get("name"), str)
            or not function["name"].strip()
        ):
            raise ProviderError("llama.cpp returned an invalid tool call")
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(
                    arguments, parse_constant=_reject_non_standard_constant
                )
            except (json.JSONDecodeError, ValueError):
                raise ProviderError("llama.cpp returned invalid tool arguments") from None
        if not isinstance(arguments, dict):
            raise ProviderError("llama.cpp returned invalid tool arguments")
        return ToolCall(call_id, function["name"], arguments)

    def _request(self, method: str, path: str, payload: object | None = None) -> Any:
        try:
            data = (
                None
                if payload is None
                else json.dumps(payload, allow_nan=False).encode("utf-8")
            )
        except (TypeError, ValueError):
            raise ProviderError("llama.cpp request has an invalid JSON shape") from None
        if data is not None and len(data) > 1_048_576:
            raise ProviderError("llama.cpp request exceeds the size limit")
        request = Request(
            f"{self.endpoint}{path}",
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(1_048_577)
        except HTTPError:
            raise ProviderError("llama.cpp request was rejected") from None
        except (TimeoutError, URLError, OSError):
            raise ProviderError("llama.cpp is unavailable") from None
        if len(raw) > 1_048_576:
            raise ProviderError("llama.cpp response exceeds the size limit")
        try:
            return json.loads(
                raw.decode("utf-8"), parse_constant=_reject_non_standard_constant
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise ProviderError("llama.cpp returned invalid JSON") from None
