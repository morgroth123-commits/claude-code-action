from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from chatmpd.defaults import (
    eso_scan_summary,
    system_snapshot_summary,
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


if __name__ == "__main__":
    unittest.main()
