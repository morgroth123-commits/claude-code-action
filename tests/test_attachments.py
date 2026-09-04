from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.attachments import AttachmentStore
from chatmpd.platform_db import PlatformDatabase


class AttachmentStoreTest(unittest.TestCase):
    def test_imports_managed_copy_lists_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "unsafe name#.txt"
            source.write_text("attachment body", encoding="utf-8")
            db_path = root / "platform.db"
            store = AttachmentStore(PlatformDatabase(db_path), root / "attachments")
            item = store.import_file(source, conversation_id="conv-1")
            self.assertTrue(item.path.is_file())
            self.assertNotEqual(item.path, source)
            self.assertEqual(store.list("conv-1")[0].attachment_id, item.attachment_id)

            restarted = AttachmentStore(PlatformDatabase(db_path), root / "attachments")
            self.assertEqual(restarted.list("conv-1")[0].original_name, "unsafe name#.txt")

    def test_rejects_files_over_configured_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "large.bin"
            source.write_bytes(b"x" * 32)
            store = AttachmentStore(PlatformDatabase(root / "db.sqlite"), root / "a", max_bytes=16)
            with self.assertRaisesRegex(ValueError, "too large"):
                store.import_file(source, conversation_id="conv")

