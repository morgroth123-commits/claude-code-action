"""Civitai platform MCP integration for ChatMPD."""

from __future__ import annotations

from typing import Any

from .external_tools import ExternalToolRunner
from .secrets_vault import SecretsVault


CIVITAI_MCP_ENDPOINT = "https://mcp.civitai.com/mcp"
CIVITAI_SECRET_NAME = "civitai-api-key"


class CivitaiMCP:
    """Browse Civitai anonymously; gate authenticated write/social actions."""

    def __init__(
        self,
        *,
        runner: ExternalToolRunner | None = None,
        secrets: SecretsVault | None = None,
        endpoint: str = CIVITAI_MCP_ENDPOINT,
    ) -> None:
        self.runner = runner or ExternalToolRunner(timeout_seconds=30)
        self.secrets = secrets or SecretsVault()
        self.endpoint = str(endpoint)
    def status(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "api_key_configured": CIVITAI_SECRET_NAME in self.secrets.names(),
            "browse_anonymous": True,
            "writes_require_key": True,
            "writes_require_confirmation": True,
            "generation_mcp": "separate-optional",
        }

    def _token(self) -> str | None:
        if CIVITAI_SECRET_NAME not in self.secrets.names():
            return None
        return self.secrets.get(CIVITAI_SECRET_NAME)

    def list_tools(self) -> tuple[dict[str, Any], ...]:
        return self.runner.list_mcp_http_tools(
            self.endpoint, bearer_token=None
        )

    def _is_read_only(self, tool_name: str) -> bool:
        target = str(tool_name).strip()
        for tool in self.list_tools():
            if str(tool.get("name", "")) != target:
                continue
            annotations = tool.get("annotations") or {}
            return bool(annotations.get("readOnlyHint") is True)
        return False
    def call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        confirmed: bool = False,
    ) -> dict[str, Any]:
        read_only = self._is_read_only(tool_name)
        token = self._token()
        if not read_only:
            if not token:
                raise PermissionError("Civitai write actions require a configured API key.")
            if not confirmed:
                raise PermissionError("Civitai write actions require explicit confirmation.")
        return self.runner.call_mcp_http(
            self.endpoint,
            str(tool_name),
            dict(arguments),
            bearer_token=token if (token and not read_only) else None,
        )
