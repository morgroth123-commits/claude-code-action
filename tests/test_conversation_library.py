from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from chatmpd.assistant import ConversationStore, DesktopAssistant
from chatmpd.conversation_library import ConversationLibrary
from chatmpd.platform_db import PlatformDatabase


class _Runtime:
    endpoint = "http://127.0.0.1:8080"
    def start(self) -> None: pass
    def stop(self) -> None: pass


class _Provider:
    def chat(self, messages):
        return type("Response", (), {"text": "continued"})()


class ConversationLibraryTest(unittest.TestCase):
    def test_reads_legacy_conversation_and_generates_title(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "legacy.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "conversation_id": "legacy",
                "updated_at": "2026-09-03T20:00:00+00:00",
                "messages": [{"role": "user", "content": "Scan my ESO addons for conflicts"}],
            }), encoding="utf-8")
            library = ConversationLibrary(root)
            document = library.load("legacy")
            self.assertEqual(document.title, "Scan my ESO addons for conflicts")
            self.assertFalse(document.pinned)
            self.assertEqual(document.messages[0]["role"], "user")

    def test_create_rename_pin_search_branch_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            library = ConversationLibrary(Path(directory))
            first = library.create()
            library.save_messages(first.conversation_id, [
                {"role": "user", "content": "Build a modern desktop interface"},
                {"role": "assistant", "content": "Working on it."},
            ])
            renamed = library.rename(first.conversation_id, "Modern UI")
            pinned = library.set_pinned(first.conversation_id, True)

            self.assertEqual(renamed.title, "Modern UI")
            self.assertTrue(pinned.pinned)
            self.assertEqual(library.search("modern")[0].conversation_id, first.conversation_id)

            branch = library.branch(first.conversation_id)
            self.assertNotEqual(branch.conversation_id, first.conversation_id)
            self.assertEqual(branch.messages, pinned.messages)
            self.assertIn("branch", branch.title.casefold())
            self.assertTrue(library.delete(branch.conversation_id))
            self.assertFalse(library.delete(branch.conversation_id))
    def test_list_places_pinned_first_and_assistant_can_load_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = ConversationLibrary(root)
            old = library.create()
            library.save_messages(old.conversation_id, [
                {"role": "user", "content": "First conversation"},
                {"role": "assistant", "content": "First answer"},
            ])
            newer = library.create()
            library.save_messages(newer.conversation_id, [
                {"role": "user", "content": "Second conversation"},
                {"role": "assistant", "content": "Second answer"},
            ])
            library.set_pinned(old.conversation_id, True)

            summaries = library.list()
            self.assertEqual(summaries[0].conversation_id, old.conversation_id)
            assistant = DesktopAssistant(
                runtime=_Runtime(),
                provider_factory=lambda endpoint: _Provider(),
                conversation_store=ConversationStore(root),
            )
            assistant.load_conversation(newer.conversation_id)
            self.assertEqual(assistant.conversation_id, newer.conversation_id)
            self.assertEqual(assistant.messages[-1]["content"], "Second answer")
            assistant.chat("Continue")
            reloaded = library.load(newer.conversation_id)
            self.assertEqual(reloaded.messages[-1]["content"], "continued")

    def test_history_survives_restart_and_new_chat_never_deletes_old_chat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            library = ConversationLibrary(root)
            saved = library.create([
                {"role": "user", "content": "Remember this permanently"},
                {"role": "assistant", "content": "I will keep this chat."},
            ])

            restarted = ConversationLibrary(root)
            restored = restarted.load(saved.conversation_id)
            self.assertEqual(restored.messages[0]["content"], "Remember this permanently")

            assistant = DesktopAssistant(
                runtime=_Runtime(),
                provider_factory=lambda endpoint: _Provider(),
                conversation_store=ConversationStore(root),
            )
            assistant.load_conversation(saved.conversation_id)
            new_id = assistant.new_conversation()
            self.assertNotEqual(new_id, saved.conversation_id)
            self.assertEqual(restarted.load(saved.conversation_id).messages, restored.messages)


if __name__ == "__main__":
    unittest.main()


class ConversationMetadataDatabaseTest(unittest.TestCase):
    def test_existing_json_is_backfilled_and_sidebar_listing_uses_sqlite_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            root.mkdir()
            path = root / "legacy.json"
            path.write_text(json.dumps({
                "conversation_id": "legacy",
                "title": "Legacy chat",
                "pinned": True,
                "workspace": "C:/project",
                "created_at": "2026-09-01T00:00:00+00:00",
                "updated_at": "2026-09-02T00:00:00+00:00",
                "messages": [{"role": "user", "content": "find the old answer"}],
            }), encoding="utf-8")
            database = PlatformDatabase(Path(directory) / "chatmpd.db")
            library = ConversationLibrary(root, database=database)

            path.write_text("{broken json", encoding="utf-8")
            summaries = library.list()

            self.assertEqual(summaries[0].conversation_id, "legacy")
            self.assertEqual(summaries[0].workspace, "C:/project")

    def test_search_uses_conversation_fts_after_save(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            database = PlatformDatabase(Path(directory) / "chatmpd.db")
            library = ConversationLibrary(root, database=database)
            document = library.create([
                {"role": "user", "content": "diagnose the impossible audio crackle"},
                {"role": "assistant", "content": "I found the receiver issue."},
            ])

            library._path(document.conversation_id).write_text("{broken", encoding="utf-8")
            matches = library.search("receiver")

            self.assertEqual(matches[0].conversation_id, document.conversation_id)

    def test_assistant_chat_save_keeps_sqlite_search_metadata_current(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            library = ConversationLibrary(root)
            document = library.create([
                {"role": "user", "content": "Initial request"},
                {"role": "assistant", "content": "Initial answer"},
            ])
            assistant = DesktopAssistant(
                runtime=_Runtime(),
                provider_factory=lambda endpoint: _Provider(),
                conversation_store=ConversationStore(root),
            )
            assistant.load_conversation(document.conversation_id)
            assistant.chat("Continue with receiver diagnostics")

            library._path(document.conversation_id).write_text("{broken", encoding="utf-8")
            matches = library.search("continued")

            self.assertEqual(matches[0].conversation_id, document.conversation_id)


class ConversationRecoveryProtocolTest(unittest.TestCase):
    def test_failed_projection_sync_is_reconciled_from_committed_json_on_restart(self) -> None:
        import sqlite3
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            database = PlatformDatabase(Path(directory) / "chatmpd.db")
            library = ConversationLibrary(root, database=database)
            document = library.create([
                {"role": "user", "content": "Initial request"},
                {"role": "assistant", "content": "Initial answer"},
            ])
            updated_messages = [
                {"role": "user", "content": "Store the durable repair token"},
                {"role": "assistant", "content": "projection-repair-token"},
            ]

            with patch.object(
                library, "_upsert_metadata",
                side_effect=sqlite3.OperationalError("database is locked"),
            ):
                with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                    library.save_messages(document.conversation_id, updated_messages)

            committed = json.loads(
                library._path(document.conversation_id).read_text(encoding="utf-8")
            )
            self.assertEqual(committed["messages"][-1]["content"], "projection-repair-token")

            restarted = ConversationLibrary(root, database=database)
            matches = restarted.search("projection-repair-token")
            self.assertEqual(matches[0].conversation_id, document.conversation_id)

    def test_conversation_store_save_uses_the_same_recoverable_projection_protocol(self) -> None:
        import sqlite3
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            library = ConversationLibrary(root)
            document = library.create([
                {"role": "user", "content": "Initial request"},
                {"role": "assistant", "content": "Initial answer"},
            ])
            store = ConversationStore(root)
            original = ConversationLibrary._upsert_metadata
            failed = False

            def fail_once(instance, candidate):
                nonlocal failed
                if not failed and any(
                    item.get("content") == "store-repair-token" for item in candidate.messages
                ):
                    failed = True
                    raise sqlite3.OperationalError("database is locked")
                return original(instance, candidate)
            with patch.object(ConversationLibrary, "_upsert_metadata", new=fail_once):
                with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                    store.save(document.conversation_id, [
                        {"role": "user", "content": "Continue"},
                        {"role": "assistant", "content": "store-repair-token"},
                    ])

            restarted = ConversationLibrary(root)
            matches = restarted.search("store-repair-token")
            self.assertEqual(matches[0].conversation_id, document.conversation_id)

    def test_delete_recovers_if_projection_cleanup_fails_after_json_is_removed(self) -> None:
        import sqlite3
        from contextlib import contextmanager
        from unittest.mock import patch

        from chatmpd.attachments import AttachmentStore

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "conversations"
            database = PlatformDatabase(base / "chatmpd.db")
            library = ConversationLibrary(root, database=database)
            document = library.create()
            attachment = AttachmentStore(database, base / "attachments").import_bytes(
                b"temporary", original_name="note.txt",
                conversation_id=document.conversation_id,
            )
            original_connect = database.connect
            calls = 0

            @contextmanager
            def fail_second_connect():
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise sqlite3.OperationalError("database is locked")
                with original_connect() as connection:
                    yield connection

            with patch.object(database, "connect", new=fail_second_connect):
                with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                    library.delete(document.conversation_id)

            self.assertFalse(library._path(document.conversation_id).exists())
            self.assertTrue(attachment.path.exists())

            restarted = ConversationLibrary(root, database=database)
            self.assertNotIn(
                document.conversation_id,
                {item.conversation_id for item in restarted.list()},
            )
            self.assertEqual(restarted.search("New chat"), ())
            self.assertFalse(attachment.path.exists())

class ConversationRecoveryEdgeCaseTest(unittest.TestCase):
    def test_invalid_pending_record_ids_are_cleared_without_blocking_startup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "conversations"
            database = PlatformDatabase(base / "chatmpd.db")
            with database.connect() as connection:
                for namespace in ("conversation_sync", "conversation_delete"):
                    for record_id in ("", "..", "bad/name"):
                        connection.execute(
                            "INSERT INTO platform_records(namespace, record_id, payload, updated_at) VALUES (?, ?, ?, ?)",
                            (namespace, record_id, "{}", "2026-09-06T00:00:00+00:00"),
                        )
                connection.commit()

            ConversationLibrary(root, database=database)

            with database.connect() as connection:
                remaining = connection.execute(
                    "SELECT namespace, record_id FROM platform_records WHERE namespace IN (?, ?)",
                    ("conversation_sync", "conversation_delete"),
                ).fetchall()
            self.assertEqual(remaining, [])

    def test_save_snapshot_propagates_transient_read_oserror_without_overwrite(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "conversations"
            library = ConversationLibrary(root)
            document = library.create([
                {"role": "user", "content": "Original request"},
                {"role": "assistant", "content": "Original answer"},
            ])
            path = library._path(document.conversation_id)
            before = path.read_text(encoding="utf-8")

            with patch.object(library, "_read_path", side_effect=OSError("sharing violation")):
                with self.assertRaisesRegex(OSError, "sharing violation"):
                    library.save_snapshot(document.conversation_id, [
                        {"role": "user", "content": "Replacement request"},
                        {"role": "assistant", "content": "Replacement answer"},
                    ])

            self.assertEqual(path.read_text(encoding="utf-8"), before)
