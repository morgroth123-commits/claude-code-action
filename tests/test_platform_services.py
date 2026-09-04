from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.model_registry import ModelRegistry
from chatmpd.platform_paths import PlatformPaths
from chatmpd.platform_services import build_platform_services


class PlatformServicesTest(unittest.TestCase):
    def test_summary_and_retrieval_context_use_persistent_memory_and_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            services = build_platform_services(
                paths=PlatformPaths(root),
                model_registry=ModelRegistry(()),
                hardware_probe=lambda: None,
            )
            services.memory.add("User prefers verification evidence", kind="preference")
            guide = root / "guide.md"
            guide.write_text("HarvestMap stores ESO resource locations.", encoding="utf-8")
            services.knowledge.ingest(guide)
            context = services.retrieval_context("verification HarvestMap")
            self.assertIn("verification evidence", context)
            self.assertIn("HarvestMap", context)

    def test_explicit_remember_instruction_is_saved_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            services = build_platform_services(
                paths=PlatformPaths(Path(directory)),
                model_registry=ModelRegistry(()),
                hardware_probe=lambda: None,
            )
            saved = services.capture_explicit_memory(
                "Remember that I prefer the dark theme for ChatMPD."
            )
            self.assertIsNotNone(saved)
            self.assertIn("dark theme", services.memory.list()[0].content)
            duplicate = services.capture_explicit_memory(
                "Remember that I prefer the dark theme for ChatMPD."
            )
            self.assertIsNone(duplicate)
            summary = services.summary()
            self.assertEqual(summary["memory_count"], 1)
            self.assertIn("capabilities", summary)
            self.assertIn("bionic", summary)


if __name__ == "__main__":
    unittest.main()
