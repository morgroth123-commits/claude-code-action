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
