from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from chatmpd.external_tools import ExternalToolRunner


class ExternalToolRunnerTest(unittest.TestCase):
    def test_plugin_and_cli_are_bounded_json_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugin.py"
            plugin.write_text(
                "import json,sys\np=json.load(sys.stdin)\n"
                "json.dump({'answer': p['text'].upper()}, sys.stdout)\n",
                encoding="utf-8",
            )
            runner = ExternalToolRunner(timeout_seconds=5, max_output_bytes=4096)
            result = runner.run_plugin(plugin, {"text": "hello"})
            self.assertEqual(result, {"answer": "HELLO"})

            cli = runner.run_cli([sys.executable, "-c", "print('ok')"])
            self.assertEqual(cli.exit_code, 0)
            self.assertEqual(cli.stdout.strip(), "ok")

    def test_http_requires_explicit_network_permission(self) -> None:
        runner = ExternalToolRunner()
        with self.assertRaisesRegex(PermissionError, "network"):
            runner.run_http("https://example.invalid/tool", {"x": 1})

    def test_mcp_stdio_initializes_and_calls_one_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "mcp.py"
            script.write_text(
                "import json,sys\n"
                "for line in sys.stdin:\n"
                " r=json.loads(line); m=r.get('method'); i=r.get('id')\n"
                " if m=='initialize': out={'jsonrpc':'2.0','id':i,'result':{'protocolVersion':'2025-06-18','capabilities':{},'serverInfo':{'name':'test','version':'1'}}}\n"
                " elif m=='tools/call': out={'jsonrpc':'2.0','id':i,'result':{'content':[{'type':'text','text':'pong'}]}}\n"
                " else: continue\n"
                " print(json.dumps(out), flush=True)\n",
                encoding="utf-8",
            )
            runner = ExternalToolRunner(timeout_seconds=5)
            result = runner.call_mcp(
                [sys.executable, str(script)], "ping", {"value": 1}
            )
            self.assertEqual(result["content"][0]["text"], "pong")


if __name__ == "__main__":
    unittest.main()
