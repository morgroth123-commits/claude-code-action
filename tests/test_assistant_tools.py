from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from chatmpd.assistant import ConversationStore, DesktopAssistant
from chatmpd.llamacpp import ToolCall


class _Runtime:
    endpoint = "http://127.0.0.1:8080"
    def start(self): pass
    def stop(self): pass


class ToolAwareAssistantTest(unittest.TestCase):
    def test_model_can_use_bounded_tool_then_answer_without_persisting_tool_payload(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            calls = []

            class Provider:
                def chat(self, messages, tools=None):
                    calls.append((messages, tools))
                    if len(calls) == 1:
                        return SimpleNamespace(
                            text="", tool_calls=(ToolCall("call-1", "ext_echo", {"input": "hello"}),)
                        )
                    return SimpleNamespace(text="Tool says hello", tool_calls=())

            invoked = []
            assistant = DesktopAssistant(
                runtime=_Runtime(),
                provider_factory=lambda _endpoint: Provider(),
                conversation_store=ConversationStore(Path(folder)),
                tool_provider=lambda _prompt: [{
                    "type": "function",
                    "function": {
                        "name": "ext_echo",
                        "description": "Echo safely",
                        "parameters": {
                            "type": "object",
                            "properties": {"input": {"type": "string"}},
                            "required": ["input"],
                        },
                    },
                }],
                tool_runner=lambda name, arguments: invoked.append((name, arguments)) or {"echo": "hello"},
            )
            turn = assistant.chat("Use the echo tool")
            self.assertEqual(turn.assistant, "Tool says hello")
            self.assertEqual(turn.tools_used, ("ext_echo",))
            self.assertEqual(invoked, [("ext_echo", {"input": "hello"})])
            tool_messages = [item for item in calls[1][0] if item.get("role") == "tool"]
            self.assertEqual(len(tool_messages), 1)
            saved = (Path(folder) / f"{assistant.conversation_id}.json").read_text(encoding="utf-8")
            self.assertNotIn("call-1", saved)
            self.assertNotIn('"echo": "hello"', saved)

    def test_tool_round_limit_fails_closed(self) -> None:
        class Provider:
            def chat(self, messages, tools=None):
                return SimpleNamespace(text="", tool_calls=(ToolCall("again", "loop", {}),))
        assistant = DesktopAssistant(
            runtime=_Runtime(), provider_factory=lambda _endpoint: Provider(),
            tool_provider=lambda _prompt: [{"type": "function", "function": {
                "name": "loop", "description": "Loop", "parameters": {"type": "object"}}}],
            tool_runner=lambda _name, _arguments: {"ok": True}, max_tool_rounds=2,
        )
        with self.assertRaisesRegex(RuntimeError, "tool-call limit"):
            assistant.chat("loop")


if __name__ == "__main__":
    unittest.main()
