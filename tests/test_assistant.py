from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from chatmpd.assistant import ConversationStore, DesktopAssistant


class _Runtime:
    endpoint = "http://127.0.0.1:8080"

    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1


class _Provider:
    def __init__(self) -> None:
        self.requests: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]]) -> SimpleNamespace:
        self.requests.append(messages)
        return SimpleNamespace(text=f"Answer {len(self.requests)}")


class DesktopAssistantTest(unittest.TestCase):
    def test_chat_reuses_runtime_keeps_context_and_persists_locally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = _Runtime()
            provider = _Provider()
            assistant = DesktopAssistant(
                runtime=runtime,
                provider_factory=lambda endpoint: provider,
                conversation_store=ConversationStore(Path(directory)),
            )

            first = assistant.chat("Hello")
            second = assistant.chat("What did I say?")

            self.assertEqual(first.assistant, "Answer 1")
            self.assertEqual(second.assistant, "Answer 2")
            self.assertEqual(runtime.starts, 2)
            self.assertEqual(provider.requests[1][-3]["content"], "Hello")
            self.assertEqual(provider.requests[1][-2]["content"], "Answer 1")
            saved = Path(directory) / f"{assistant.conversation_id}.json"
            payload = json.loads(saved.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["messages"]), 4)

            assistant.close()
            assistant.close()
            self.assertEqual(runtime.stops, 1)

    def test_new_conversation_drops_old_context_without_deleting_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = _Provider()
            assistant = DesktopAssistant(
                runtime=_Runtime(),
                provider_factory=lambda endpoint: provider,
                conversation_store=ConversationStore(Path(directory)),
            )
            assistant.chat("Old topic")
            old_id = assistant.conversation_id

            new_id = assistant.new_conversation()
            assistant.chat("New topic")

            self.assertNotEqual(old_id, new_id)
            self.assertNotIn("Old topic", [m["content"] for m in provider.requests[-1]])
            self.assertTrue((Path(directory) / f"{old_id}.json").is_file())
            self.assertTrue((Path(directory) / f"{new_id}.json").is_file())

    def test_task_uses_same_managed_runtime_after_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = _Runtime()
            calls: list[object] = []

            def preflight(workspace: Path, task: str) -> str:
                calls.append(("preflight", workspace, task))
                return "prepared"

            def run(workspace: Path, task: str, **options: object) -> str:
                calls.append(("run", workspace, task, options))
                return "outcome"

            assistant = DesktopAssistant(
                runtime=runtime,
                preflight_runner=preflight,
                task_runner=run,
            )
            result = assistant.run_task(root, "Fix it")

            self.assertEqual(result, "outcome")
            self.assertEqual(runtime.starts, 1)
            self.assertEqual(calls[1][3]["endpoint"], runtime.endpoint)
            self.assertEqual(calls[1][3]["prepared"], "prepared")


if __name__ == "__main__":
    unittest.main()
