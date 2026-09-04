from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.memory import MemoryStore
from chatmpd.platform_db import PlatformDatabase


class MemoryStoreTest(unittest.TestCase):
    def test_memory_survives_restart_and_supports_search_update_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "platform.db"
            first = MemoryStore(PlatformDatabase(path))
            memory = first.add(
                "Prefer concise evidence-backed answers",
                kind="preference",
                source="conversation:abc",
            )
            self.assertEqual(first.search("evidence")[0].memory_id, memory.memory_id)
            updated = first.update(memory.memory_id, "Prefer concise verified answers", pinned=True)
            self.assertTrue(updated.pinned)

            second = MemoryStore(PlatformDatabase(path))
            restored = second.get(memory.memory_id)
            self.assertEqual(restored.content, "Prefer concise verified answers")
            self.assertEqual(restored.source, "conversation:abc")
            self.assertTrue(second.delete(memory.memory_id))
            self.assertEqual(second.search("verified"), ())
