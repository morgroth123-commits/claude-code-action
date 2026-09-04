from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.activity import ActivityLog
from chatmpd.performance import (
    AdaptivePerformanceController,
    PerformanceAnalyzer,
    PerformanceEvidence,
    PerformanceStore,
    ProcessPressure,
    VaderOptimizer,
)
from chatmpd.permissions import PermissionProfileStore
from chatmpd.platform_db import PlatformDatabase


GIB = 1024 ** 3
HIGH_PERFORMANCE = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"


class PerformanceAnalyzerTest(unittest.TestCase):
    def make_database(self, root: Path) -> PlatformDatabase:
        return PlatformDatabase(root / "platform.db")

    def test_scores_bottleneck_bounds_processes_and_persists_report(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = self.make_database(Path(folder))
            evidence = PerformanceEvidence(                cpu_percent=18.0,
                memory_total_bytes=32 * GIB,
                memory_available_bytes=24 * GIB,
                disk_total_bytes=1000 * GIB,
                disk_free_bytes=500 * GIB,
                gpu={"utilization_percent": 30.0, "vram_total_mib": 12288, "vram_used_mib": 12000,
                     "temperature_c": 68.0, "power_w": 145.0, "power_limit_w": 170.0},
                processes=tuple(ProcessPressure(f"p{index}", index, 80 - index, index * GIB)
                                for index in range(12)),
                power_plan_guid="baseline-guid",
                power_plan_name="Balanced",
                workloads=("chatmpd",),
            )
            analyzer = PerformanceAnalyzer(
                PerformanceStore(database), evidence_probe=lambda: evidence
            )
            report = analyzer.analyze()
            self.assertEqual(report.bottleneck, "vram")
            self.assertLessEqual(len(report.top_processes), 8)
            for score in (report.overall_score, report.gaming_score,
                          report.ai_score, report.balanced_score):
                self.assertGreaterEqual(score, 0)
                self.assertLessEqual(score, 100)
            self.assertTrue(any(item.key == "vram" for item in report.findings))
            self.assertEqual(PerformanceStore(database).list()[0].report_id, report.report_id)

    def test_missing_gpu_telemetry_reduces_confidence_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = self.make_database(Path(folder))
            evidence = PerformanceEvidence(                cpu_percent=45.0,
                memory_total_bytes=16 * GIB,
                memory_available_bytes=8 * GIB,
                disk_total_bytes=500 * GIB,
                disk_free_bytes=100 * GIB,
                gpu={}, processes=(),
                power_plan_guid="guid", power_plan_name="Balanced", workloads=(),
            )
            report = PerformanceAnalyzer(
                PerformanceStore(database), evidence_probe=lambda: evidence
            ).analyze()
            self.assertLess(report.telemetry_confidence, 1.0)
            self.assertIsInstance(report.ai_score, int)
            self.assertNotEqual(report.bottleneck, "gpu")


class VaderOptimizerTest(unittest.TestCase):
    def test_modes_are_reversible_and_analyze_never_mutates(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = PlatformDatabase(Path(folder) / "platform.db")
            current = {"guid": "baseline-guid"}
            writes: list[str] = []
            releases: list[str] = []

            def set_plan(guid: str) -> None:
                writes.append(guid)
                current["guid"] = guid

            optimizer = VaderOptimizer(
                database=database,
                permissions=PermissionProfileStore(database),
                activity=ActivityLog(database),
                power_getter=lambda: (current["guid"], "Current"),
                power_setter=set_plan,
                release_runtime=lambda: releases.append("released"),
            )
            optimizer.apply("analyze")
            self.assertEqual(writes, [])
            gaming = optimizer.apply("gaming")
            self.assertEqual(gaming.mode, "gaming")
            self.assertEqual(writes[-1], HIGH_PERFORMANCE)
            self.assertEqual(releases, ["released"])
            restored = optimizer.restore()
            self.assertEqual(restored.mode, "restored")
            self.assertEqual(writes[-1], "baseline-guid")
    def test_adaptive_controller_only_changes_on_transitions(self) -> None:
        class FakeOptimizer:
            def __init__(self) -> None:
                self.calls: list[str] = []
            def apply(self, mode: str):
                self.calls.append(mode)
                return mode

        game = {"running": False}
        optimizer = FakeOptimizer()
        controller = AdaptivePerformanceController(
            optimizer, workload_probe=lambda: game["running"], base_mode="ai"
        )
        self.assertEqual(controller.tick(), "ai")
        self.assertEqual(optimizer.calls, ["ai"])
        self.assertEqual(controller.tick(), "ai")
        self.assertEqual(optimizer.calls, ["ai"])
        game["running"] = True
        self.assertEqual(controller.tick(), "gaming")
        self.assertEqual(optimizer.calls[-1], "gaming")
        self.assertEqual(controller.tick(), "gaming")
        self.assertEqual(optimizer.calls.count("gaming"), 1)
        game["running"] = False
        self.assertEqual(controller.tick(), "ai")
        self.assertEqual(optimizer.calls, ["ai", "gaming", "ai"])


if __name__ == "__main__":
    unittest.main()
