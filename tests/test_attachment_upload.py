from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.attachments import AttachmentStore
from chatmpd.conversation_library import ConversationLibrary
from chatmpd.platform_db import PlatformDatabase


class AttachmentUploadTest(unittest.TestCase):
    def test_import_bytes_is_managed_persistent_and_filename_safe(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = AttachmentStore(
                PlatformDatabase(root / "platform.db"), root / "files", max_bytes=1024
            )
            record = store.import_bytes(
                b"hello file", original_name="../notes.txt",
                conversation_id="conv-1", content_type="text/plain",
            )
            self.assertEqual(record.original_name, "notes.txt")
            self.assertEqual(record.path.read_bytes(), b"hello file")
            self.assertEqual(store.list("conv-1")[0].attachment_id, record.attachment_id)

            restarted = AttachmentStore(
                PlatformDatabase(root / "platform.db"), root / "files", max_bytes=1024
            )
            self.assertEqual(restarted.get(record.attachment_id).original_name, "notes.txt")

    def test_import_bytes_enforces_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = AttachmentStore(PlatformDatabase(root / "db.sqlite"), root / "files", max_bytes=4)
            with self.assertRaisesRegex(ValueError, "too large"):
                store.import_bytes(b"12345", original_name="big.txt", conversation_id="c")


class AttachmentConversationLifecycleTest(unittest.TestCase):
    def test_deleting_conversation_removes_attachment_rows_and_files(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = PlatformDatabase(root / "platform.db")
            library = ConversationLibrary(root / "conversations", database=database)
            store = AttachmentStore(database, root / "attachments", max_bytes=1024)
            conversation = library.create()
            record = store.import_bytes(
                b"temporary", original_name="note.txt",
                conversation_id=conversation.conversation_id,
            )

            self.assertTrue(record.path.exists())
            self.assertTrue(library.delete(conversation.conversation_id))
            self.assertFalse(record.path.exists())
            self.assertEqual(store.list(conversation.conversation_id), ())



class _PlatformWithAttachments:
    def __init__(self, store: AttachmentStore) -> None:
        self.attachments = store


class AttachmentConversationApiTest(unittest.TestCase):
    def setUp(self) -> None:
        import base64
        import http.client
        import json
        import time

        from chatmpd.orchestrator import CommandResult
        from chatmpd.web_service import WebAppService

        self.base64 = base64
        self.http_client = http.client
        self.json = json
        self.time = time
        self.CommandResult = CommandResult
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.assets = root / "web"
        self.assets.mkdir()
        (self.assets / "index.html").write_text("<main>shell</main>", encoding="utf-8")
        self.database = PlatformDatabase(root / "platform.db")
        self.library = ConversationLibrary(root / "conversations", database=self.database)
        self.store = AttachmentStore(self.database, root / "files", max_bytes=1024)

        class Orchestrator:
            def __init__(self) -> None:
                self.assistant = type(
                    "A",
                    (),
                    {
                        "load_conversation": lambda self, cid: cid,
                        "release_runtime": lambda self: None,
                    },
                )()
                self.router = type(
                    "R",
                    (),
                    {"classify": lambda self, text: type("D", (), {"capability": "chat"})()},
                )()
                self.calls = []

            def command(self, text, workspace=None):
                self.calls.append((text, workspace))
                if "fix" in text.casefold() and not workspace:
                    return CommandResult(
                        "coding",
                        "Choose a project folder so ChatMPD can edit and verify the code safely.",
                        {
                            "status": "needs_context",
                            "status_label": "Checking project",
                            "needs_context": {
                                "kind": "workspace",
                                "message": "A project folder is required for coding work.",
                            },
                            "suggested_action": "choose_workspace",
                        },
                    )
                return CommandResult("chat", f"done:{text}", {"status": "completed"})

        self.orchestrator = Orchestrator()
        self.service = WebAppService(
            self.orchestrator,
            self.library,
            assets_root=self.assets,
            platform_services=_PlatformWithAttachments(self.store),
        )
        self.service.start()

    def tearDown(self) -> None:
        self.service.stop()
        self.temp.cleanup()

    def _request(self, method: str, path: str, payload: object | None = None):
        connection = self.http_client.HTTPConnection(
            "127.0.0.1", self.service.port, timeout=3
        )
        body = None if payload is None else self.json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, self.json.loads(data or b"{}")

    def _wait_job(self, job_id: str) -> dict:
        deadline = self.time.time() + 4
        while self.time.time() < deadline:
            status, payload = self._request("GET", f"/api/jobs/{job_id}")
            self.assertEqual(status, 200)
            if payload["status"] not in {"queued", "running", "cancelling"}:
                return payload
            self.time.sleep(0.02)
        self.fail("job did not finish")

    def test_upload_list_and_delete_attachment_api(self) -> None:
        conversation = self.library.create()
        cid = conversation.conversation_id
        encoded = self.base64.b64encode(b"hello note").decode("ascii")
        status, created = self._request(
            "POST",
            f"/api/conversations/{cid}/attachments",
            {
                "filename": "note.txt",
                "content_type": "text/plain",
                "data": encoded,
            },
        )
        self.assertEqual(status, 201)
        attachment_id = created["attachment_id"]
        self.assertEqual(created["original_name"], "note.txt")
        self.assertEqual(created["size_bytes"], 10)
        self.assertNotIn("path", created)

        status, items = self._request("GET", f"/api/conversations/{cid}/attachments")
        self.assertEqual(status, 200)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["attachment_id"], attachment_id)
        self.assertNotIn("path", items[0])

        other = self.library.create()
        status, denied = self._request(
            "DELETE",
            f"/api/conversations/{other.conversation_id}/attachments/{attachment_id}",
        )
        self.assertIn(status, {403, 400})
        self.assertTrue(self.store.get(attachment_id).path.exists())

        status, deleted = self._request(
            "DELETE", f"/api/conversations/{cid}/attachments/{attachment_id}"
        )
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])
        self.assertEqual(self.store.list(cid), ())

    def test_oversize_upload_returns_user_safe_error(self) -> None:
        conversation = self.library.create()
        # Store max is 1024; send larger payload via API.
        blob = b"x" * 2048
        encoded = self.base64.b64encode(blob).decode("ascii")
        status, payload = self._request(
            "POST",
            f"/api/conversations/{conversation.conversation_id}/attachments",
            {"filename": "big.txt", "data": encoded, "content_type": "text/plain"},
        )
        self.assertEqual(status, 400)
        self.assertIn("large", payload["error"].casefold())
        self.assertNotIn("Traceback", payload["error"])

    def test_job_rejects_unknown_attachment_ids(self) -> None:
        conversation = self.library.create()
        status, payload = self._request(
            "POST",
            "/api/jobs",
            {
                "text": "Read this file",
                "conversation_id": conversation.conversation_id,
                "attachment_ids": ["missing-id"],
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("attachment", payload["error"].casefold())

    def test_job_includes_text_attachment_context_and_needs_context_status(self) -> None:
        conversation = self.library.create()
        record = self.store.import_bytes(
            b"formula = 2 + 2",
            original_name="calc.txt",
            conversation_id=conversation.conversation_id,
            content_type="text/plain",
        )
        status, accepted = self._request(
            "POST",
            "/api/jobs",
            {
                "text": "Please fix the calculator total",
                "conversation_id": conversation.conversation_id,
                "attachment_ids": [record.attachment_id],
            },
        )
        self.assertEqual(status, 202)
        final = self._wait_job(accepted["job_id"])
        self.assertEqual(final["status"], "needs_context")
        self.assertEqual(final["status_label"], "Checking project")
        self.assertEqual(
            final["result"]["details"]["suggested_action"], "choose_workspace"
        )
        self.assertTrue(self.orchestrator.calls)
        command_text = self.orchestrator.calls[0][0]
        self.assertIn("formula = 2 + 2", command_text)
        self.assertIn("calc.txt", command_text)
