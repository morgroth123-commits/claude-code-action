from __future__ import annotations

import http.client
import json
import tempfile
import unittest
from pathlib import Path

from chatmpd.conversation_library import ConversationLibrary
from chatmpd.model_registry import ModelRegistry
from chatmpd.performance import PerformanceEvidence
from chatmpd.platform_paths import PlatformPaths
from chatmpd.platform_services import build_platform_services
from chatmpd.web_service import WebAppService


class _Assistant:
    conversation_id = ""
    def close(self): pass


class _Orchestrator:
    def __init__(self, platform):
        self.assistant = _Assistant()
        self.platform_services = platform


class WebPlatformTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.power_guid = "baseline-guid"
        evidence = PerformanceEvidence(20.0, 16*1024**3, 12*1024**3, 100*1024**3, 50*1024**3, {}, (), "baseline-guid", "Balanced", ())
        def set_power(guid): self.power_guid = guid
        self.services = build_platform_services(
            paths=PlatformPaths(root / "platform"),
            model_registry=ModelRegistry(()),
            hardware_probe=lambda: None, performance_probe=lambda: evidence,
            power_getter=lambda: (self.power_guid, "Test plan"), power_setter=set_power,
        )
        assets = root / "web"
        assets.mkdir()
        (assets / "index.html").write_text("platform shell", encoding="utf-8")
        self.service = WebAppService(
            _Orchestrator(self.services),
            ConversationLibrary(root / "conversations"),
            assets_root=assets,
            platform_services=self.services,
        )
        self.service.start()

    def tearDown(self) -> None:
        self.service.stop()
        self.temp.cleanup()

    def request(self, method: str, path: str, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.service.port, timeout=3)
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        connection.request(method, path, body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        data = json.loads(response.read() or b"{}")
        connection.close()
        return response.status, data

    def test_summary_memory_prompt_and_capability_surfaces(self) -> None:
        status, summary = self.request("GET", "/api/platform/summary")
        self.assertEqual(status, 200)
        self.assertIn("bionic", summary)
        status, memory = self.request("POST", "/api/platform/memory", {"content": "Use concise output"})
        self.assertEqual(status, 201)
        self.assertIn("memory_id", memory)
        status, memories = self.request("GET", "/api/platform/memory")
        self.assertEqual(status, 200)
        self.assertEqual(memories[0]["content"], "Use concise output")
        status, prompts = self.request("GET", "/api/platform/prompts")
        self.assertEqual(status, 200)
        self.assertIn("coding", prompts["templates"])
        status, capabilities = self.request("GET", "/api/platform/capabilities")
        self.assertEqual(status, 200)
        ids = {item["capability_id"] for item in capabilities}
        self.assertIn("lmstudio", ids)
        self.assertIn("bionic", ids)

    def test_knowledge_workflow_automation_and_doctor_surfaces(self) -> None:
        source = Path(self.temp.name) / "knowledge.md"
        source.write_text("persistent local knowledge", encoding="utf-8")
        status, item = self.request("POST", "/api/platform/knowledge", {"path": str(source)})
        self.assertEqual(status, 201)
        self.assertEqual(item["title"], "knowledge.md")
        status, workflow = self.request("POST", "/api/platform/workflows", {
            "name": "Health", "command": "check system health"
        })
        self.assertEqual(status, 201)
        self.assertIn("workflow_id", workflow)
        status, doctor = self.request("GET", "/api/platform/doctor")
        self.assertEqual(status, 200)
        self.assertIn("checks", doctor)


    def test_performance_analysis_profiles_restore_and_adaptive_surfaces(self) -> None:
        status, initial = self.request("GET", "/api/platform/performance")
        self.assertEqual(status, 200)
        self.assertEqual(initial["status"]["active_mode"], "balanced")
        status, report = self.request("POST", "/api/platform/performance/analyze", {})
        self.assertEqual(status, 200)
        self.assertIn("overall_score", report)
        status, applied = self.request("POST", "/api/platform/performance/apply", {"mode": "gaming"})
        self.assertEqual(status, 200)
        self.assertEqual(applied["mode"], "gaming")
        status, adaptive = self.request("POST", "/api/platform/performance/adaptive", {"enabled": True, "base_mode": "ai", "start_thread": False})
        self.assertEqual(status, 200)
        self.assertTrue(adaptive["adaptive_enabled"])
        status, restored = self.request("POST", "/api/platform/performance/restore", {})
        self.assertEqual(status, 200)
        self.assertEqual(restored["power_plan_guid"], "baseline-guid")

if __name__ == "__main__":
    unittest.main()
