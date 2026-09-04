from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.activity import ActivityLog
from chatmpd.performance import (
    AdaptivePerformanceController,
    PerformanceAnalyzer,
    PerformanceCenter,
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


class PerformanceCenterTest(unittest.TestCase):
    def test_status_history_and_adaptive_tick_are_exposed(self) -> None:
        class Analyzer:
            def analyze(self): return "report"
            store = type("Store", (), {"list": lambda self, limit=50: ("old",)})()
        class Optimizer:
            def __init__(self): self.calls = []
            def status(self): return {"active_mode": "balanced"}
            def apply(self, mode, confirmed=False): self.calls.append(mode); return mode
            def restore(self, confirmed=False): return "restored"
            def bind_runtime(self, callback): self.callback = callback
        game = {"running": False}
        optimizer = Optimizer()
        center = PerformanceCenter(Analyzer(), optimizer, workload_probe=lambda: game["running"], poll_seconds=60)
        self.assertEqual(center.analyze(), "report")
        self.assertEqual(center.history(), ("old",))
        self.assertFalse(center.status()["adaptive_enabled"])
        center.set_adaptive(True, base_mode="ai", start_thread=False)
        self.assertEqual(optimizer.calls, ["ai"])
        self.assertEqual(center.tick_adaptive(), "ai")
        game["running"] = True
        self.assertEqual(center.tick_adaptive(), "gaming")
        center.set_adaptive(False)
        self.assertFalse(center.status()["adaptive_enabled"])
        self.assertEqual(optimizer.calls[-1], "ai")

    def test_manual_profile_records_before_after_score_delta(self) -> None:
        reports = iter([
            type("Report", (), {"overall_score": 50, "report_id": "before"})(),
            type("Report", (), {"overall_score": 68, "report_id": "after"})(),
        ])
        class Analyzer:
            def analyze(self): return next(reports)
            store = type("Store", (), {"list": lambda self, limit=50: ()})()
        class Optimizer:
            def status(self): return {"active_mode": "balanced"}
            def apply(self, mode, confirmed=False): return type("Result", (), {"mode": mode})()
            def restore(self, confirmed=False): return type("Result", (), {"mode": "restored"})()
            def bind_runtime(self, callback): pass
        center = PerformanceCenter(Analyzer(), Optimizer(), workload_probe=lambda: False)
        center.apply("ai")
        comparison = center.status()["last_optimization"]
        self.assertEqual(comparison["before_score"], 50)
        self.assertEqual(comparison["after_score"], 68)
        self.assertEqual(comparison["score_delta"], 18)

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

            current["guid"] = "new-user-plan"
            optimizer.apply("gaming")
            current["guid"] = HIGH_PERFORMANCE
            optimizer.restore()
            self.assertEqual(writes[-1], "new-user-plan")

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


class PerformancePressureSignalsTest(unittest.TestCase):
    def test_real_pressure_signals_drive_bottleneck_not_free_space_alone(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = PlatformDatabase(Path(folder) / "platform.db")
            evidence = PerformanceEvidence(
                cpu_percent=12.0, memory_total_bytes=32 * GIB,
                memory_available_bytes=22 * GIB, disk_total_bytes=500 * GIB,
                disk_free_bytes=45 * GIB, gpu={"utilization_percent": 5.0,
                "vram_total_mib": 12288, "vram_used_mib": 2000}, processes=(),
                power_plan_guid="guid", power_plan_name="High performance", workloads=(),
                commit_percent=42.0, pagefile_percent=3.0,
                disk_active_percent=2.0, disk_queue_length=0.0, disk_bytes_per_sec=1_000_000.0,
            )
            report = PerformanceAnalyzer(
                PerformanceStore(database), evidence_probe=lambda: evidence
            ).analyze()
            self.assertNotEqual(report.bottleneck, "storage")
            self.assertFalse(any(item.key == "storage" for item in report.findings))

    def test_disk_queue_and_commit_pressure_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = PlatformDatabase(Path(folder) / "platform.db")
            evidence = PerformanceEvidence(
                cpu_percent=20.0, memory_total_bytes=32 * GIB,
                memory_available_bytes=18 * GIB, disk_total_bytes=500 * GIB,
                disk_free_bytes=250 * GIB, gpu={}, processes=(),
                power_plan_guid="guid", power_plan_name="Balanced", workloads=(),
                commit_percent=92.0, pagefile_percent=55.0,
                disk_active_percent=98.0, disk_queue_length=6.0, disk_bytes_per_sec=80_000_000.0,
            )
            report = PerformanceAnalyzer(
                PerformanceStore(database), evidence_probe=lambda: evidence
            ).analyze()
            keys = {item.key for item in report.findings}
            self.assertIn("commit", keys)
            self.assertIn("disk", keys)


class PerformanceProbeParsingTest(unittest.TestCase):
    def test_parses_windows_commit_pagefile_and_disk_counters(self) -> None:
        from chatmpd.performance import parse_windows_pressure_payload
        payload = {
            "memory": {"PercentCommittedBytesInUse": 61, "PagesPersec": 3},
            "disk": {"PercentDiskTime": 27, "CurrentDiskQueueLength": 2,
                     "DiskBytesPersec": 12_500_000},
            "pagefile": [{"AllocatedBaseSize": 8192, "CurrentUsage": 2048}],
        }
        parsed = parse_windows_pressure_payload(payload)
        self.assertEqual(parsed["commit_percent"], 61.0)
        self.assertEqual(parsed["pagefile_percent"], 25.0)
        self.assertEqual(parsed["disk_active_percent"], 27.0)
        self.assertEqual(parsed["disk_queue_length"], 2.0)
        self.assertEqual(parsed["disk_bytes_per_sec"], 12_500_000.0)

    def test_high_io_process_is_kept_in_competing_processes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = PlatformDatabase(Path(folder) / "platform.db")
            processes = [ProcessPressure(f"cpu{n}", n, 90 - n, 200 * 1024**2)
                         for n in range(10)]
            processes.append(ProcessPressure("iohog", 99, 1.0, 100 * 1024**2,
                                             io_bytes_per_sec=900 * 1024**2))
            evidence = PerformanceEvidence(
                cpu_percent=20, memory_total_bytes=32*GIB, memory_available_bytes=20*GIB,
                disk_total_bytes=500*GIB, disk_free_bytes=250*GIB, gpu={},
                processes=tuple(processes), power_plan_guid="g", power_plan_name="Balanced",
                workloads=(), commit_percent=40, disk_active_percent=20,
            )
            report = PerformanceAnalyzer(PerformanceStore(database),
                                         evidence_probe=lambda: evidence).analyze()
            self.assertIn("iohog", {item.name for item in report.top_processes})

    def test_parses_process_io_pressure_from_windows_perf_rows(self) -> None:
        from chatmpd.performance import parse_process_pressure_rows
        rows = [{"Name": "ChatMPD#2", "IDProcess": 42,
                 "PercentProcessorTime": 120, "WorkingSet": 512 * 1024**2,
                 "IODataBytesPersec": 64 * 1024**2}]
        parsed = parse_process_pressure_rows(rows, logical_cpus=6)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].name, "ChatMPD")
        self.assertEqual(parsed[0].pid, 42)
        self.assertAlmostEqual(parsed[0].cpu_percent, 20.0)
        self.assertEqual(parsed[0].io_bytes_per_sec, 64 * 1024**2)


class PerformanceProfileSemanticsTest(unittest.TestCase):
    def test_balanced_profile_uses_windows_balanced_and_restore_returns_user_baseline(self) -> None:
        from chatmpd.performance import BALANCED_GUID
        with tempfile.TemporaryDirectory() as folder:
            database = PlatformDatabase(Path(folder) / "platform.db")
            current = {"guid": HIGH_PERFORMANCE}
            writes = []
            def setter(guid: str) -> None:
                writes.append(guid); current["guid"] = guid
            optimizer = VaderOptimizer(
                database=database, permissions=PermissionProfileStore(database),
                activity=ActivityLog(database),
                power_getter=lambda: (current["guid"], "Current"), power_setter=setter,
            )
            result = optimizer.apply("balanced")
            self.assertEqual(result.power_plan_guid, BALANCED_GUID)
            self.assertEqual(writes[-1], BALANCED_GUID)
            restored = optimizer.restore()
            self.assertEqual(restored.power_plan_guid, HIGH_PERFORMANCE)
            self.assertEqual(writes[-1], HIGH_PERFORMANCE)


class PerformanceWindowsContextTest(unittest.TestCase):
    def test_parses_gaming_startup_and_disk_health_context(self) -> None:
        from chatmpd.performance import parse_windows_pressure_payload
        payload = {
            "memory": {}, "disk": {}, "pagefile": [],
            "game_mode": 1, "hags": 2, "startup_count": 17,
            "physical_disks": [
                {"FriendlyName": "NVMe", "MediaType": "SSD",
                 "HealthStatus": "Healthy", "OperationalStatus": "OK"},
            ],
        }
        parsed = parse_windows_pressure_payload(payload)
        self.assertEqual(parsed["gaming_config"]["game_mode"], "enabled")
        self.assertEqual(parsed["gaming_config"]["hags"], "enabled")
        self.assertEqual(parsed["startup_count"], 17)
        self.assertIn("NVMe", parsed["disk_health"][0])
        self.assertIn("Healthy", parsed["disk_health"][0])

    def test_unhealthy_disk_and_large_startup_load_become_findings(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = PlatformDatabase(Path(folder) / "platform.db")
            evidence = PerformanceEvidence(
                cpu_percent=10, memory_total_bytes=32*GIB, memory_available_bytes=20*GIB,
                disk_total_bytes=500*GIB, disk_free_bytes=250*GIB, gpu={}, processes=(),
                power_plan_guid="g", power_plan_name="Balanced", workloads=(),
                commit_percent=45, disk_active_percent=2,
                startup_count=40, disk_health=("NVMe · Warning · Degraded",),
            )
            report = PerformanceAnalyzer(PerformanceStore(database),
                                         evidence_probe=lambda: evidence).analyze()
            keys = {item.key for item in report.findings}
            self.assertIn("startup", keys)
            self.assertIn("disk-health", keys)


class PerformanceSourceQualityTest(unittest.TestCase):
    def test_performance_module_compiles_without_syntax_warnings(self) -> None:
        import warnings
        source_path = Path(__file__).resolve().parents[1] / "chatmpd" / "performance.py"
        source = source_path.read_text(encoding="utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            compile(source, str(source_path), "exec")


class PerformanceBottleneckSemanticsTest(unittest.TestCase):
    def test_healthy_machine_reports_no_active_bottleneck(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            database = PlatformDatabase(Path(folder) / "platform.db")
            evidence = PerformanceEvidence(
                cpu_percent=15, memory_total_bytes=32*GIB, memory_available_bytes=20*GIB,
                disk_total_bytes=500*GIB, disk_free_bytes=200*GIB,
                gpu={"utilization_percent": 10, "vram_total_mib": 12288,
                     "vram_used_mib": 3000}, processes=(),
                power_plan_guid=HIGH_PERFORMANCE, power_plan_name="High performance",
                workloads=(), commit_percent=48, pagefile_percent=4,
                disk_active_percent=3, disk_queue_length=0,
            )
            report = PerformanceAnalyzer(PerformanceStore(database),
                                         evidence_probe=lambda: evidence).analyze()
            self.assertEqual(report.bottleneck, "none")
            self.assertEqual(report.findings, ())
