from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.civitai import CivitaiMCP
from chatmpd.platform_db import PlatformDatabase
from chatmpd.secrets_vault import SecretsVault


class FakeRunner:
    def __init__(self) -> None:
        self.calls = []
        self.tools = [
            {"name": "search_models", "annotations": {"readOnlyHint": True}},
            {"name": "create_post", "annotations": {"readOnlyHint": False}},
        ]

    def list_mcp_http_tools(self, endpoint, *, bearer_token=None):
        self.calls.append(("list", endpoint, bearer_token))
        return tuple(self.tools)

    def call_mcp_http(self, endpoint, tool_name, arguments, *, bearer_token=None):
        self.calls.append(("call", endpoint, tool_name, dict(arguments), bearer_token))
        return {"content": [{"type": "text", "text": "ok"}]}


class CivitaiMCPTest(unittest.TestCase):
    def make_client(self, root: Path):
        database = PlatformDatabase(root / "platform.db")
        vault = SecretsVault(database)
        runner = FakeRunner()
        return CivitaiMCP(runner=runner, secrets=vault), runner, vault

    def test_anonymous_browse_and_optional_key_status(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            client, runner, vault = self.make_client(Path(folder))
            status = client.status()
            self.assertEqual(status["endpoint"], "https://mcp.civitai.com/mcp")
            self.assertFalse(status["api_key_configured"])
            tools = client.list_tools()
            self.assertEqual([item["name"] for item in tools], ["search_models", "create_post"])
            self.assertIsNone(runner.calls[-1][2])
            vault.set("civitai-api-key", "secret-token")
            self.assertTrue(client.status()["api_key_configured"])
            client.list_tools()
            self.assertIsNone(runner.calls[-1][2])
            client.call("search_models", {"query": "flux"})
            self.assertIsNone(runner.calls[-1][-1])

    def test_read_tool_is_anonymous_but_write_requires_key_and_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            client, runner, vault = self.make_client(Path(folder))
            result = client.call("search_models", {"query": "flux"})
            self.assertEqual(result["content"][0]["text"], "ok")
            self.assertIsNone(runner.calls[-1][-1])

            with self.assertRaisesRegex(PermissionError, "API key"):
                client.call("create_post", {"title": "x"}, confirmed=True)
            vault.set("civitai-api-key", "secret-token")
            with self.assertRaisesRegex(PermissionError, "confirmation"):
                client.call("create_post", {"title": "x"})
            client.call("create_post", {"title": "x"}, confirmed=True)
            self.assertEqual(runner.calls[-1][-1], "secret-token")

    def test_unknown_tool_fails_closed_as_write(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            client, _runner, vault = self.make_client(Path(folder))
            vault.set("civitai-api-key", "secret-token")
            with self.assertRaisesRegex(PermissionError, "confirmation"):
                client.call("future_new_tool", {})


if __name__ == "__main__":
    unittest.main()
