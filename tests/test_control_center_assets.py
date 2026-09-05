from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "chatmpd" / "web"


class ControlCenterAssetTest(unittest.TestCase):
    def test_control_center_has_major_platform_surfaces(self) -> None:
        page = (WEB / "index.html").read_text(encoding="utf-8")
        for required in (
            'id="control-center"', 'id="control-dialog"',
            'data-control-section="overview"', 'data-control-section="memory"',
            'data-control-section="knowledge"', 'data-control-section="capabilities"',
            'data-control-section="models"', 'data-control-section="performance"',
            'data-control-section="workflows"',
            'data-control-section="automations"', 'data-control-section="recovery"',
            'data-control-section="prompts"', 'data-control-section="diagnostics"',
            'data-control-section="sharing"',
        ):
            self.assertIn(required, page)

    def test_control_center_script_fetches_platform_data_and_uses_text_content(self) -> None:
        script = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("openControlCenter", script)
        self.assertIn("loadControlSection", script)
        self.assertIn("/api/platform/", script)
        self.assertIn("renderPerformanceSection", script)
        self.assertIn("/api/platform/performance", script)
        self.assertIn("gaming", script)
        self.assertIn("adaptive", script)
        self.assertIn("textContent", script)
        self.assertNotIn("innerHTML", script)


if __name__ == "__main__":
    unittest.main()


class CivitaiControlCenterAssetTest(unittest.TestCase):
    def test_skills_tools_surface_exposes_civitai_mcp_controls(self) -> None:
        script = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("Civitai", script)
        self.assertIn("/api/platform/civitai", script)
        self.assertIn("civitai-api-key", script)
        self.assertIn("List Civitai tools", script)
        self.assertNotIn("innerHTML", script)


class PerformanceControlCenterAssetTest(unittest.TestCase):
    def test_performance_section_renders_pressure_and_io_signals(self) -> None:
        script = (WEB / "app.js").read_text(encoding="utf-8")
        for required in (
            "commit_percent", "pagefile_percent", "disk_active_percent",
            "disk_queue_length", "disk_bytes_per_sec", "io_bytes_per_sec",
        ):
            self.assertIn(required, script)


class PerformanceWindowsContextAssetTest(unittest.TestCase):
    def test_performance_section_renders_windows_context_read_only(self) -> None:
        script = (WEB / "app.js").read_text(encoding="utf-8")
        for required in ("gaming_config", "startup_count", "disk_health"):
            self.assertIn(required, script)


class PerformanceGuidanceAssetTest(unittest.TestCase):
    def test_performance_section_offers_one_click_guidance_and_comparison(self) -> None:
        script = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("Optimize for current workload", script)
        self.assertIn("recommendations", script)
        self.assertIn("last_optimization", script)
        self.assertIn("score_delta", script)
