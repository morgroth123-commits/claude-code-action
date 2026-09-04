from __future__ import annotations

import http.client
import json
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event

from chatmpd.conversation_library import ConversationLibrary
from chatmpd.orchestrator import CommandResult
from chatmpd.web_service import WebAppService


class _Assistant:
    def __init__(self) -> None:
        self.conversation_id = ""
        self.loaded: list[str] = []
        self.releases = 0

    def load_conversation(self, conversation_id: str) -> str:
        self.conversation_id = conversation_id
        self.loaded.append(conversation_id)
        return conversation_id

    def release_runtime(self) -> None:
        self.releases += 1


class _Router:
    def classify(self, text: str):
        capability = "chat" if "chat" in text.casefold() else "system"
        return type("Decision", (), {"capability": capability})()


class _Orchestrator:
    def __init__(self) -> None:
        self.assistant = _Assistant()
        self.router = _Router()
        self.started = Event()
        self.release = Event()
        self.block = False
        self.calls: list[tuple[str, str | None]] = []

    def command(self, text: str, workspace: str | None = None) -> CommandResult:
        self.calls.append((text, workspace))
        self.started.set()
        if self.block:
            self.release.wait(3)
        return CommandResult("system", f"done:{text}", {"status": "ok"})


class WebServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.assets = root / "web"
        self.assets.mkdir()
        (self.assets / "index.html").write_text("<main>ChatMPD modern shell</main>", encoding="utf-8")
        (self.assets / "chatmpd-192.png").write_bytes(b"png")
        self.library = ConversationLibrary(root / "conversations")
        self.orchestrator = _Orchestrator()
        self.service = WebAppService(
            self.orchestrator,
            self.library,
            assets_root=self.assets,
        )
        self.service.start()

    def tearDown(self) -> None:
        self.orchestrator.release.set()
        self.service.stop()
        self.temp.cleanup()

    def _request(self, method: str, path: str, payload: object | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.service.port, timeout=3)
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        content_type = response.getheader("Content-Type", "")
        connection.close()
        if "application/json" in content_type:
            return response.status, json.loads(data or b"{}")
        return response.status, data.decode("utf-8")

    def _wait_job(self, job_id: str) -> dict[str, object]:
        deadline = time.time() + 4
        while time.time() < deadline:
            status, payload = self._request("GET", f"/api/jobs/{job_id}")
            self.assertEqual(status, 200)
            if payload["status"] not in {"queued", "running", "cancelling"}:
                return payload
            time.sleep(0.02)
        self.fail("job did not finish")

    def test_loopback_static_shell_and_conversation_crud(self) -> None:
        self.assertTrue(self.service.url.startswith("http://127.0.0.1:"))
        status, page = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("modern shell", page)
        status, icon = self._request("GET", "/chatmpd-192.png")
        self.assertEqual(status, 200)
        self.assertEqual(icon, "png")

        status, created = self._request("POST", "/api/conversations", {})
        self.assertEqual(status, 201)
        conversation_id = created["conversation_id"]
        self._request("POST", f"/api/conversations/{conversation_id}/rename", {"title": "Pinned memory"})
        self._request("POST", f"/api/conversations/{conversation_id}/pin", {"pinned": True})
        status, items = self._request("GET", "/api/conversations")
        self.assertEqual(status, 200)
        self.assertEqual(items[0]["title"], "Pinned memory")
        self.assertTrue(items[0]["pinned"])

    def test_job_returns_immediately_and_persists_completed_turn(self) -> None:
        conversation = self.library.create()
        status, accepted = self._request("POST", "/api/jobs", {
            "text": "Check system health",
            "conversation_id": conversation.conversation_id,
        })
        self.assertEqual(status, 202)
        job_id = accepted["job_id"]
        final = self._wait_job(job_id)
        self.assertEqual(final["status"], "completed")
        self.assertEqual(final["result"]["message"], "done:Check system health")
        restored = ConversationLibrary(self.library.root).load(conversation.conversation_id)
        self.assertEqual(restored.messages[-2]["content"], "Check system health")
        self.assertEqual(restored.messages[-1]["content"], "done:Check system health")
        self.assertEqual(self.orchestrator.assistant.loaded[-1], conversation.conversation_id)

    def test_overlapping_work_is_rejected_until_active_job_finishes(self) -> None:
        self.orchestrator.block = True
        conversation = self.library.create()
        status, first = self._request("POST", "/api/jobs", {
            "text": "Check system health",
            "conversation_id": conversation.conversation_id,
        })
        self.assertEqual(status, 202)
        self.assertTrue(self.orchestrator.started.wait(1))
        status, second = self._request("POST", "/api/jobs", {
            "text": "Another command",
            "conversation_id": conversation.conversation_id,
        })
        self.assertEqual(status, 409)
        self.assertIn("busy", second["error"].casefold())
        self.orchestrator.release.set()
        self.assertEqual(self._wait_job(first["job_id"])["status"], "completed")

    def test_cancelled_job_never_reports_success(self) -> None:
        self.orchestrator.block = True
        conversation = self.library.create()
        status, accepted = self._request("POST", "/api/jobs", {
            "text": "chat about local models",
            "conversation_id": conversation.conversation_id,
        })
        self.assertEqual(status, 202)
        self.assertTrue(self.orchestrator.started.wait(1))
        status, cancelling = self._request(
            "POST", f"/api/jobs/{accepted['job_id']}/cancel", {}
        )
        self.assertEqual(status, 202)
        self.assertIn(cancelling["status"], {"cancelling", "cancelled"})
        self.orchestrator.release.set()
        final = self._wait_job(accepted["job_id"])
        self.assertEqual(final["status"], "cancelled")
        self.assertNotIn("result", final)
        self.assertGreaterEqual(self.orchestrator.assistant.releases, 1)


if __name__ == "__main__":
    unittest.main()
