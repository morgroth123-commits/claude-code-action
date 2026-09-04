"""Bounded subprocess, HTTP, and MCP adapters for ChatMPD extensions."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class ProcessResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str


class ExternalToolRunner:
    def __init__(self, *, timeout_seconds: float = 30.0, max_output_bytes: int = 1_048_576) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_output_bytes < 1024:
            raise ValueError("max_output_bytes must be at least 1024")
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_bytes = int(max_output_bytes)

    def run_plugin(self, path: Path, payload: dict[str, Any]) -> dict[str, Any]:
        plugin = Path(path).resolve()
        if not plugin.is_file():
            raise FileNotFoundError(plugin)
        result = self._run(
            [sys.executable, str(plugin)],
            input_text=json.dumps(payload, ensure_ascii=False),
        )
        if result.exit_code != 0:
            raise RuntimeError(f"Plugin failed with exit code {result.exit_code}: {result.stderr[:300]}")
        try:
            value = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as error:
            raise RuntimeError("Plugin did not return valid JSON.") from error
        if not isinstance(value, dict):
            raise RuntimeError("Plugin result must be a JSON object.")
        return value

    def run_cli(
        self,
        argv: Sequence[str],
        *,
        input_text: str | None = None,
    ) -> ProcessResult:
        if not argv or not str(argv[0]).strip():
            raise ValueError("CLI argv cannot be empty.")
        return self._run([str(item) for item in argv], input_text=input_text)

    def run_http(
        self,
        endpoint: str,
        payload: dict[str, Any],
        *,
        allow_network: bool = False,
    ) -> dict[str, Any]:
        if not allow_network:
            raise PermissionError("External network access is disabled until explicitly allowed.")
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            str(endpoint), data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read(self.max_output_bytes + 1)
        if len(raw) > self.max_output_bytes:
            raise RuntimeError("External HTTP response exceeded the output limit.")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("External HTTP response was not valid JSON.") from error
        if not isinstance(value, dict):
            raise RuntimeError("External HTTP response must be a JSON object.")
        return value

    def list_mcp_http_tools(
        self, endpoint: str, *, bearer_token: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        session, protocol = self._initialize_mcp_http(endpoint, bearer_token=bearer_token)
        result, _session = self._mcp_http_request(
            endpoint, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            bearer_token=bearer_token, session_id=session, protocol_version=protocol,
        )
        tools = (result or {}).get("result", {}).get("tools", [])
        if not isinstance(tools, list):
            raise RuntimeError("MCP tools/list result was malformed.")
        return tuple(dict(item) for item in tools if isinstance(item, dict))

    def call_mcp_http(
        self, endpoint: str, tool_name: str, arguments: dict[str, Any],
        *, bearer_token: str | None = None,
    ) -> dict[str, Any]:
        session, protocol = self._initialize_mcp_http(endpoint, bearer_token=bearer_token)
        payload = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                   "params": {"name": str(tool_name), "arguments": dict(arguments)}}
        response, _session = self._mcp_http_request(
            endpoint, payload, bearer_token=bearer_token, session_id=session, protocol_version=protocol
        )
        if response is None or "error" in response:
            raise RuntimeError("Remote MCP tool call failed.")
        value = response.get("result")
        if not isinstance(value, dict):
            raise RuntimeError("MCP tool result must be a JSON object.")
        return value

    def call_mcp(
        self,
        argv: Sequence[str],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        initialize = {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "ChatMPD", "version": "0.2"},
            },
        }
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        call = {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": str(tool_name), "arguments": dict(arguments)},
        }
        input_text = "\n".join(json.dumps(item, separators=(",", ":")) for item in (initialize, initialized, call)) + "\n"
        result = self._run([str(item) for item in argv], input_text=input_text)
        if result.exit_code != 0:
            raise RuntimeError(f"MCP server failed with exit code {result.exit_code}: {result.stderr[:300]}")
        response: dict[str, Any] | None = None
        for line in result.stdout.splitlines():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get("id") == 2:
                response = message
                break
        if response is None:
            raise RuntimeError("MCP server did not return the tool response.")
        if "error" in response:
            raise RuntimeError(f"MCP tool error: {response['error']}")
        value = response.get("result")
        if not isinstance(value, dict):
            raise RuntimeError("MCP tool result must be a JSON object.")
        return value

    def _initialize_mcp_http(
        self, endpoint: str, *, bearer_token: str | None
    ) -> tuple[str | None, str]:
        request = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "ChatMPD", "version": "0.3"}}}
        response, session = self._mcp_http_request(endpoint, request, bearer_token=bearer_token)
        if response is None or "error" in response:
            raise RuntimeError("Remote MCP initialize failed.")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Remote MCP initialize result was malformed.")
        protocol = str(result.get("protocolVersion") or "2025-06-18")
        self._mcp_http_request(
            endpoint, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            bearer_token=bearer_token, session_id=session, protocol_version=protocol,
        )
        return session, protocol

    def _mcp_http_request(
        self, endpoint: str, payload: dict[str, Any], *, bearer_token: str | None = None,
        session_id: str | None = None, protocol_version: str | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        from urllib.parse import urlsplit
        parsed = urlsplit(str(endpoint))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Remote MCP endpoint must be HTTP(S).")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Remote MCP HTTP is allowed only for loopback; external endpoints require HTTPS.")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "ChatMPD/0.3",
        }
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        if protocol_version:
            headers["MCP-Protocol-Version"] = protocol_version
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(str(endpoint), data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self.max_output_bytes + 1)
                session = response.headers.get("Mcp-Session-Id") or session_id
                content_type = response.headers.get("Content-Type", "")
        except Exception as error:
            raise RuntimeError(f"Remote MCP request failed: {type(error).__name__}") from error
        if len(raw) > self.max_output_bytes:
            raise RuntimeError("Remote MCP response exceeded the output limit.")
        if not raw:
            return None, session
        value = self._decode_mcp_http(raw, content_type)
        return value, session

    @staticmethod
    def _decode_mcp_http(raw: bytes, content_type: str) -> dict[str, Any]:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RuntimeError("Remote MCP response was not UTF-8.") from error
        if "text/event-stream" in content_type.casefold() or text.lstrip().startswith(("data:", "event:")):
            candidates = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
            for candidate in candidates:
                if not candidate or candidate == "[DONE]":
                    continue
                try:
                    value = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    return value
            raise RuntimeError("Remote MCP event stream contained no JSON-RPC message.")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise RuntimeError("Remote MCP response was not valid JSON.") from error
        if not isinstance(value, dict):
            raise RuntimeError("Remote MCP response must be a JSON object.")
        return value

    def _run(self, argv: list[str], *, input_text: str | None = None) -> ProcessResult:
        try:
            completed = subprocess.run(
                argv,
                input=input_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError(f"External tool timed out after {self.timeout_seconds:g}s") from error
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if len(stdout.encode("utf-8", errors="replace")) > self.max_output_bytes:
            raise RuntimeError("External tool stdout exceeded the output limit.")
        if len(stderr.encode("utf-8", errors="replace")) > self.max_output_bytes:
            stderr = stderr.encode("utf-8", errors="replace")[: self.max_output_bytes].decode("utf-8", errors="replace")
        return ProcessResult(tuple(argv), int(completed.returncode), stdout, stderr)
