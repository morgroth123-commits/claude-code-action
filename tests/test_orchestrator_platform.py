from __future__ import annotations

import unittest
from types import SimpleNamespace

from chatmpd.orchestrator import ChatMPDOrchestrator


class _Assistant:
    def __init__(self): self.saved = []
    def chat(self, text): return SimpleNamespace(assistant="ok")
    def close(self): pass


class _Platform:
    def __init__(self): self.captured = []
    def capture_explicit_memory(self, text):
        self.captured.append(text)
        return None


class OrchestratorPlatformTest(unittest.TestCase):
    def test_plain_language_command_offers_explicit_memory_to_platform(self) -> None:
        platform = _Platform()
        orchestrator = ChatMPDOrchestrator(
            assistant=_Assistant(),
            platform_services=platform,
        )
        result = orchestrator.command("Remember that my UI theme is dark")
        self.assertEqual(result.message, "ok")
        self.assertEqual(platform.captured, ["Remember that my UI theme is dark"])


if __name__ == "__main__":
    unittest.main()
