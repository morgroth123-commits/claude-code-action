from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.platform_db import PlatformDatabase


class PlatformDatabaseSchemaTest(unittest.TestCase):
    def test_initialization_creates_assistant_first_indexes_and_conversation_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = PlatformDatabase(Path(directory) / "chatmpd.db")
            with database.connect() as connection:
                indexes = {
                    str(row["name"])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='index'"
                    ).fetchall()
                }
                tables = {
                    str(row["name"])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }

            self.assertTrue({
                "idx_platform_records_namespace_updated_at",
                "idx_memories_pinned_updated_at",
                "uq_knowledge_sources_path",
                "idx_knowledge_sources_updated_at",
                "uq_knowledge_chunks_source_index",
                "idx_conversations_list",
            }.issubset(indexes))
            self.assertIn("conversations", tables)
            self.assertIn("conversations_fts", tables)


if __name__ == "__main__":
    unittest.main()


class _FakeConnection:
    def __init__(self) -> None:
        self.row_factory = None
        self.statements: list[str] = []
        self.closed = False

    def execute(self, statement: str, *args):
        self.statements.append(statement)
        return self

    def close(self) -> None:
        self.closed = True


class PlatformDatabaseConnectionTest(unittest.TestCase):
    def test_regular_connect_sets_session_pragmas_without_reissuing_wal(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            database = PlatformDatabase(Path(directory) / "chatmpd.db")
            fake = _FakeConnection()
            with patch("chatmpd.platform_db.sqlite3.connect", return_value=fake):
                with database.connect() as connection:
                    self.assertIsNotNone(connection)

            normalized = [item.replace(" ", "").casefold() for item in fake.statements]
            self.assertIn("pragmaforeign_keys=on", normalized)
            self.assertTrue(any(item.startswith("pragmabusy_timeout=") for item in normalized))
            self.assertFalse(any("journal_mode" in item for item in normalized))

    def test_connect_retries_transient_lock_and_then_succeeds(self) -> None:
        import sqlite3
        from unittest.mock import patch

        database = PlatformDatabase.__new__(PlatformDatabase)
        database.path = Path("retry-test.db")
        fake = _FakeConnection()
        locked = sqlite3.OperationalError("database is locked")
        with patch(
            "chatmpd.platform_db.sqlite3.connect", side_effect=[locked, fake]
        ) as connector, patch("time.sleep") as sleeper:
            with database.connect() as connection:
                self.assertIsNotNone(connection)

        self.assertEqual(connector.call_count, 2)
        sleeper.assert_called_once()

    def test_connect_does_not_retry_unrelated_operational_error(self) -> None:
        import sqlite3
        from unittest.mock import patch

        database = PlatformDatabase.__new__(PlatformDatabase)
        database.path = Path("retry-test.db")
        failure = sqlite3.OperationalError("unable to open database file")
        with patch(
            "chatmpd.platform_db.sqlite3.connect", side_effect=failure
        ) as connector, patch("time.sleep") as sleeper:
            with self.assertRaisesRegex(sqlite3.OperationalError, "unable to open"):
                with database.connect():
                    pass

        self.assertEqual(connector.call_count, 1)
        sleeper.assert_not_called()


class PlatformDatabaseOperationRetryTest(unittest.TestCase):
    def test_execute_retries_transient_lock_without_hiding_other_sql_errors(self) -> None:
        import sqlite3
        from unittest.mock import patch

        class LockingConnection(_FakeConnection):
            def __init__(self) -> None:
                super().__init__()
                self.update_attempts = 0

            def execute(self, statement: str, *args):
                if statement.startswith("UPDATE"):
                    self.update_attempts += 1
                    if self.update_attempts == 1:
                        raise sqlite3.OperationalError("database table is locked")
                return super().execute(statement, *args)

        database = PlatformDatabase.__new__(PlatformDatabase)
        database.path = Path("retry-test.db")
        fake = LockingConnection()
        with patch("chatmpd.platform_db.sqlite3.connect", return_value=fake), patch("time.sleep") as sleeper:
            with database.connect() as connection:
                connection.execute("UPDATE records SET value=1")

        self.assertEqual(fake.update_attempts, 2)
        sleeper.assert_called_once()
