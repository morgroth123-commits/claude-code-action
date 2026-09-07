from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from chatmpd.assistant import ConversationStore, DesktopAssistant
from chatmpd.llamacpp import ChatResponse
from chatmpd.local_model import LocalCodingModel


class _Runtime:
    endpoint = "http://127.0.0.1:8080"

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class _ChatProvider:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def chat(self, messages: list[dict[str, str]]) -> SimpleNamespace:
        self.messages = messages
        return SimpleNamespace(text="ok")


class _CodingProvider:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def chat(self, messages: list[dict[str, object]], **_kwargs: object) -> ChatResponse:
        self.messages = messages
        return ChatResponse("1. Inspect", (), "stop")


class PromptIntegrationTest(unittest.TestCase):
    def test_standard_chat_receives_shared_autonomy_doctrine(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = _ChatProvider()
            assistant = DesktopAssistant(
                runtime=_Runtime(),
                provider_factory=lambda _endpoint: provider,
                conversation_store=ConversationStore(Path(directory)),
            )
            assistant.chat("hello")
            system = str(provider.messages[0]["content"]).casefold()
            self.assertIn("autonomy is the default", system)
            self.assertIn("critical", system)

    def test_coding_agent_receives_shared_autonomy_doctrine(self) -> None:
        provider = _CodingProvider()
        model = LocalCodingModel(provider, allowed_commands=[])
        model.next_turn({"task": "inspect", "events": []})
        system = str(provider.messages[0]["content"]).casefold()
        self.assertIn("autonomy is the default", system)
        self.assertIn("fresh verification", system)


if __name__ == "__main__":
    unittest.main()

class AssistantFirstPromptIntegrationTest(unittest.TestCase):
    def test_general_prompt_says_ordinary_language_is_enough_and_selection_is_automatic(self) -> None:
        from chatmpd.doctrine import general_assistant_prompt
        prompt = general_assistant_prompt().casefold()
        self.assertIn("ordinary language", prompt)
        self.assertIn("automatically", prompt)
        self.assertIn("tools", prompt)
