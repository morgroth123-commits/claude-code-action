from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.model_registry import ModelRegistry
from chatmpd.performance import PerformanceEvidence
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


    def test_performance_center_is_constructed_with_injected_probes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = PerformanceEvidence(
                10.0, 16 * 1024**3, 12 * 1024**3,
                100 * 1024**3, 50 * 1024**3, {}, (), "guid", "Balanced", (),
            )
            services = build_platform_services(
                paths=PlatformPaths(Path(directory)), model_registry=ModelRegistry(()),
                hardware_probe=lambda: None, performance_probe=lambda: evidence,
                power_getter=lambda: ("guid", "Balanced"), power_setter=lambda _guid: None,
            )
            report = services.performance.analyze()
            self.assertGreater(report.overall_score, 0)
            self.assertIn("performance", services.summary())
            self.assertEqual(services.summary()["performance"]["history_count"], 1)
            services.close()

if __name__ == "__main__":
    unittest.main()
