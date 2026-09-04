from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from types import SimpleNamespace

from chatmpd.defaults import (
    build_default_orchestrator,
    eso_scan_summary,
    system_snapshot_summary,
    performance_command_summary,
    vortex_report_summary,
)


class DefaultSpecialistSummaryTest(unittest.TestCase):
    def test_eso_summary_is_bounded_and_evidence_based(self) -> None:
        report = SimpleNamespace(
            manifests=tuple(range(173)),
            issues=(
                SimpleNamespace(code="dependency_missing", severity="critical", addon_id="A", message="Missing B"),
                SimpleNamespace(code="old_api", severity="warning", addon_id="C", message="Old API"),
            ),
            critical_count=1,
            warning_count=1,
            repairable_count=0,
            current_api=101048,
            scanned_at="now",
        )
        summary = eso_scan_summary(report)
        self.assertEqual(summary["addon_count"], 173)
        self.assertEqual(summary["critical_count"], 1)
        self.assertEqual(summary["issues"][0]["addon_id"], "A")

    def test_vortex_summary_reports_games_without_live_database_mutation(self) -> None:
        report = SimpleNamespace(
            version="2.1.1",
            games=(
                SimpleNamespace(
                    game_id="teso", profile_count=2, mod_count=5,
                    snapshot_entries=100, snapshot_base_paths=("C:/Game",),
                ),
            ),
        )
        summary = vortex_report_summary(report)
        self.assertEqual(summary["version"], "2.1.1")
        self.assertEqual(summary["games"][0]["game_id"], "teso")
        self.assertEqual(summary["games"][0]["snapshot_entries"], 100)

    def test_system_summary_uses_human_scale_values(self) -> None:
        snapshot = SimpleNamespace(
            os_name="Windows", os_release="11", machine="AMD64", cpu_logical=6,
            memory_total_bytes=32 * 1024**3,
            memory_available_bytes=10 * 1024**3,
            disk_total_bytes=1024 * 1024**3,
            disk_free_bytes=400 * 1024**3,
            gpu={"name": "RTX 3060", "vram_total_mib": 12288, "vram_used_mib": 1000},
        )
        summary = system_snapshot_summary(snapshot)
        self.assertEqual(summary["cpu_logical"], 6)
        self.assertEqual(summary["memory_total_gib"], 32.0)
        self.assertEqual(summary["disk_free_gib"], 400.0)
        self.assertEqual(summary["gpu"]["name"], "RTX 3060")


    def test_performance_command_requires_explicit_profile_but_supports_modes(self) -> None:
        class Performance:
            def __init__(self): self.calls = []
            def analyze(self):
                self.calls.append(("analyze",))
                return SimpleNamespace(overall_score=82, gaming_score=84, ai_score=80, balanced_score=81, bottleneck="storage", findings=())
            def apply(self, mode):
                self.calls.append(("apply", mode))
                return SimpleNamespace(mode=mode, message=f"Applied {mode}", changed=True)
            def restore(self):
                self.calls.append(("restore",))
                return SimpleNamespace(mode="restored", message="Restored", changed=True)
            def set_adaptive(self, enabled, base_mode="balanced"):
                self.calls.append(("adaptive", enabled, base_mode))
                return {"adaptive_enabled": enabled, "adaptive_base_mode": base_mode}
        center = Performance()
        generic = performance_command_summary(center, "Optimize my PC performance")
        self.assertEqual(center.calls, [("analyze",)])
        self.assertIn("storage", generic["summary"])
        performance_command_summary(center, "Optimize for gaming performance")
        self.assertEqual(center.calls[-1], ("apply", "gaming"))
        performance_command_summary(center, "Restore my performance baseline")
        self.assertEqual(center.calls[-1], ("restore",))



    def test_default_orchestrator_binds_performance_runtime_release(self) -> None:
        source = inspect.getsource(build_default_orchestrator)
        self.assertIn("services.performance.bind_runtime(assistant.release_runtime)", source)

if __name__ == "__main__":
    unittest.main()


class DefaultAssistantToolWiringTest(unittest.TestCase):
    def test_default_orchestrator_wires_permission_aware_extension_tools_into_chat(self) -> None:
        source = inspect.getsource(build_default_orchestrator)
        self.assertIn("tool_provider=services.assistant_tools.tools_for_prompt", source)
        self.assertIn("tool_runner=services.assistant_tools.invoke", source)
