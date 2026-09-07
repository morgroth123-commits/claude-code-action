"""SQLite persistence shared by ChatMPD platform services."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterator

from .platform_paths import PlatformPaths


_BUSY_TIMEOUT_MS = 2_000
_LOCK_RETRY_DELAYS = (0.05, 0.15)


def _is_transient_lock(error: sqlite3.OperationalError) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    if isinstance(code, int) and (code & 0xFF) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        return True
    message = str(error).casefold()
    return "locked" in message or "busy" in message


def _with_lock_retry(operation: Callable[[], Any]) -> Any:
    for attempt in range(len(_LOCK_RETRY_DELAYS) + 1):
        try:
            return operation()
        except sqlite3.OperationalError as error:
            if not _is_transient_lock(error) or attempt >= len(_LOCK_RETRY_DELAYS):
                raise
            time.sleep(_LOCK_RETRY_DELAYS[attempt])


class _RetryingConnection:
    """Connection adapter that retries only transient SQLite lock/busy failures."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @property
    def row_factory(self) -> Any:
        return self._connection.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._connection.row_factory = value

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        return _with_lock_retry(lambda: self._connection.execute(*args, **kwargs))

    def executescript(self, *args: Any, **kwargs: Any) -> Any:
        return _with_lock_retry(lambda: self._connection.executescript(*args, **kwargs))

    def commit(self) -> None:
        _with_lock_retry(self._connection.commit)

    def close(self) -> None:
        self._connection.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class PlatformDatabase:
    def __init__(self, path: Path | None = None) -> None:
        default = PlatformPaths.default().data / "chatmpd.db"
        self.path = Path(path or default)
        self._lock = RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[_RetryingConnection]:
        raw = _with_lock_retry(
            lambda: sqlite3.connect(self.path, timeout=_BUSY_TIMEOUT_MS / 1000.0)
        )
        connection = _RetryingConnection(raw)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            self._create_core_tables(connection)
            self._create_fts_tables(connection)
            connection.commit()

    @staticmethod
    def _create_core_tables(connection: Any) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                memory_id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                kind TEXT NOT NULL,
                source TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge_sources (
                source_id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                chunk_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES knowledge_sources(source_id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL
            );
            """
        )
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS attachments (
                attachment_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                original_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                content_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_attachments_conversation
                ON attachments(conversation_id, created_at);
            CREATE TABLE IF NOT EXISTS platform_records (
                namespace TEXT NOT NULL,
                record_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(namespace, record_id)
            );
            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0, 1)),
                workspace TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                preview TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_platform_records_namespace_updated_at
                ON platform_records(namespace, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memories_pinned_updated_at
                ON memories(pinned DESC, updated_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_sources_path
                ON knowledge_sources(path);
            CREATE INDEX IF NOT EXISTS idx_knowledge_sources_updated_at
                ON knowledge_sources(updated_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_knowledge_chunks_source_index
                ON knowledge_chunks(source_id, chunk_index);
            CREATE INDEX IF NOT EXISTS idx_conversations_list
                ON conversations(pinned DESC, updated_at DESC, conversation_id DESC);
            """
        )

    @staticmethod
    def _create_fts_tables(connection: Any) -> None:
        connection.executescript(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                memory_id UNINDEXED, content, source
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                chunk_id UNINDEXED, source_id UNINDEXED, text
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
                conversation_id UNINDEXED, title, preview, message_text
            );
            """
        )
