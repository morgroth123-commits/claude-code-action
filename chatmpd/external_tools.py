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
