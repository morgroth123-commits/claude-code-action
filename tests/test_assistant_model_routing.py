from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from chatmpd.assistant import ConversationStore, DesktopAssistant
from chatmpd.model_registry import ModelRole


class _Manager:
    endpoint = "http://127.0.0.1:8080"

    def __init__(self) -> None:
        self.roles: list[ModelRole] = []
        self.stops = 0

    def activate(self, role: ModelRole) -> "_Manager":
        self.roles.append(role)
        return self

    def stop(self) -> None:
        self.stops += 1


class _Provider:
    def chat(self, _messages: object) -> SimpleNamespace:
        return SimpleNamespace(text="ok")


class AssistantModelRoutingTest(unittest.TestCase):
    def test_chat_uses_reasoning_role_and_task_uses_coding_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = _Manager()
            assistant = DesktopAssistant(
                model_manager=manager,
                provider_factory=lambda _endpoint: _Provider(),
                conversation_store=ConversationStore(root / "history"),
                preflight_runner=lambda workspace, task: "prepared",
                task_runner=lambda workspace, task, **options: options["endpoint"],
            )

            turn = assistant.chat("Think carefully about this")
            endpoint = assistant.run_task(root, "Fix the project")

            self.assertEqual(turn.assistant, "ok")
            self.assertEqual(endpoint, manager.endpoint)
            self.assertEqual(
                manager.roles,
                [ModelRole.REASONING, ModelRole.CODING],
            )
            assistant.close()
            self.assertEqual(manager.stops, 1)


if __name__ == "__main__":
    unittest.main()
