from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from chatmpd.assistant import ConversationStore, DesktopAssistant


class _Runtime:
    endpoint = "http://127.0.0.1:8080"
    def start(self): pass
    def stop(self): pass


class _Provider:
    def __init__(self): self.messages = None
    def chat(self, messages):
        self.messages = messages
        return SimpleNamespace(text="context used")


class AssistantRetrievalTest(unittest.TestCase):
    def test_retrieval_context_is_added_to_system_context_not_persisted_as_chat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = _Provider()
            assistant = DesktopAssistant(
                runtime=_Runtime(),
                provider_factory=lambda _endpoint: provider,
                conversation_store=ConversationStore(Path(directory)),
                context_provider=lambda prompt: "Relevant durable memories:\n- dark theme",
            )
            assistant.chat("What theme do I prefer?")
            self.assertIn("dark theme", provider.messages[0]["content"])
            self.assertNotIn(
                "dark theme",
                [message["content"] for message in assistant.messages],
            )


if __name__ == "__main__":
    unittest.main()
