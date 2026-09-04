from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from chatmpd.external_tools import ExternalToolRunner


class MCPHandler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *_args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).seen.append((payload, dict(self.headers)))
        method = payload.get("method")
        if method == "notifications/initialized":
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "test", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "search_models", "annotations": {"readOnlyHint": True}}]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "pong"}]}
        else:
            result = {}
        body = json.dumps({"jsonrpc": "2.0", "id": payload.get("id"), "result": result}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "session-123")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MCPHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        MCPHandler.seen = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MCPHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_address[1]}/mcp"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
    def test_lists_tools_and_preserves_session_and_bearer_header(self) -> None:
        runner = ExternalToolRunner(timeout_seconds=5)
        tools = runner.list_mcp_http_tools(self.endpoint, bearer_token="token-abc")
        self.assertEqual(tools[0]["name"], "search_models")
        methods = [item[0].get("method") for item in MCPHandler.seen]
        self.assertEqual(methods, ["initialize", "notifications/initialized", "tools/list"])
        self.assertEqual(MCPHandler.seen[0][1].get("Authorization"), "Bearer token-abc")
        self.assertEqual(MCPHandler.seen[-1][1].get("Mcp-Session-Id"), "session-123")

    def test_calls_remote_mcp_tool(self) -> None:
        runner = ExternalToolRunner(timeout_seconds=5)
        result = runner.call_mcp_http(
            self.endpoint, "search_models", {"query": "flux"}
        )
        self.assertEqual(result["content"][0]["text"], "pong")
        last = MCPHandler.seen[-1][0]
        self.assertEqual(last["method"], "tools/call")
        self.assertEqual(last["params"]["name"], "search_models")
        self.assertEqual(last["params"]["arguments"], {"query": "flux"})


if __name__ == "__main__":
    unittest.main()


class MCPHttpHeaderTest(MCPHttpTest):
    def test_uses_explicit_chatmpd_user_agent_for_remote_compatibility(self) -> None:
        ExternalToolRunner(timeout_seconds=5).list_mcp_http_tools(self.endpoint)
        self.assertTrue(MCPHandler.seen[0][1].get("User-Agent", "").startswith("ChatMPD/"))
