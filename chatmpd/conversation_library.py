"""Local persistent conversation library for ChatMPD."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from .platform_db import PlatformDatabase


def _default_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "ChatMPD" / "conversations"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _clean_messages(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    messages: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if role in {"user", "assistant", "system"} and isinstance(content, str):
            messages.append({"role": role, "content": content})
    return messages


def _title_from(messages: list[dict[str, str]]) -> str:
    for message in messages:
        if message.get("role") != "user":
            continue
        text = " ".join(message.get("content", "").split()).strip()
        if text:
            return text[:64].rstrip()
    return "New chat"


@dataclass(frozen=True)
class ConversationSummary:
    conversation_id: str
    title: str
    pinned: bool
    created_at: str
    updated_at: str
    preview: str
    workspace: str | None = None


@dataclass(frozen=True)
class ConversationDocument:
    conversation_id: str
    title: str
    pinned: bool
    created_at: str
    updated_at: str
    messages: list[dict[str, str]]
    workspace: str | None = None

    def summary(self) -> ConversationSummary:
        preview = ""
        if self.messages:
            preview = " ".join(self.messages[-1]["content"].split())[:100]
        return ConversationSummary(
            self.conversation_id, self.title, self.pinned,
            self.created_at, self.updated_at, preview, self.workspace,
        )


class ConversationLibrary:
    """Manage ChatMPD conversation documents using atomic local JSON files."""

    def __init__(
        self, root: Path | None = None, *, database: PlatformDatabase | None = None
    ) -> None:
        self.root = Path(root or _default_root())
        self._lock = RLock()
        if database is not None:
            self.database = database
        elif self.root == _default_root():
            self.database = PlatformDatabase()
        else:
            self.database = PlatformDatabase(self.root / ".chatmpd-metadata.sqlite")
        self._reconcile_pending_deletes()
        self._reconcile_pending_syncs()
        self._backfill_once()

    def create(self, messages: list[dict[str, str]] | None = None) -> ConversationDocument:
        with self._lock:
            now = _now()
            document = ConversationDocument(
                uuid4().hex, "New chat", False, now, now,
                _clean_messages(messages or []),
            )
            if document.messages:
                document = self._replace(document, title=_title_from(document.messages))
            self._write(document)
            return document

    def list(
        self, *, limit: int = 200, offset: int = 0
    ) -> tuple[ConversationSummary, ...]:
        bounded_limit = max(1, min(int(limit), 1000))
        bounded_offset = max(0, int(offset))
        with self._lock, self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM conversations
                ORDER BY pinned DESC, updated_at DESC, conversation_id DESC
                LIMIT ? OFFSET ?
                """,
                (bounded_limit, bounded_offset),
            ).fetchall()
        return tuple(self._summary_from_row(row) for row in rows)

    def load(self, conversation_id: str) -> ConversationDocument:
        with self._lock:
            return self._read_path(self._path(conversation_id))

    def save_messages(
        self, conversation_id: str, messages: list[dict[str, str]]
    ) -> ConversationDocument:
        with self._lock:
            current = self.load(conversation_id)
            cleaned = _clean_messages(messages)
            title = current.title
            if title == "New chat" and cleaned:
                title = _title_from(cleaned)
            updated = self._replace(
                current, title=title, messages=cleaned, updated_at=_now()
            )
            self._write(updated)
            return updated

    def save_snapshot(
        self, conversation_id: str, messages: list[dict[str, str]]
    ) -> ConversationDocument:
        """Persist a full transcript through the same recoverable projection path."""

        with self._lock:
            cleaned_id = str(conversation_id).strip()
            path = self._path(cleaned_id)
            cleaned = _clean_messages(messages)
            now = _now()
            try:
                current = self._read_path(path)
            except (FileNotFoundError, ValueError):
                document = ConversationDocument(
                    cleaned_id, _title_from(cleaned), False, now, now, cleaned, None
                )
            else:
                title = current.title
                if title == "New chat" and cleaned:
                    title = _title_from(cleaned)
                document = self._replace(
                    current, title=title, messages=cleaned, updated_at=now
                )
            self._write(document)
            return document

    def rename(self, conversation_id: str, title: str) -> ConversationDocument:
        cleaned = " ".join(str(title).split()).strip()
        if not cleaned:
            raise ValueError("Conversation title cannot be blank.")
        with self._lock:
            current = self.load(conversation_id)
            updated = self._replace(current, title=cleaned[:100], updated_at=_now())
            self._write(updated)
            return updated

    def set_workspace(
        self, conversation_id: str, workspace: str | None
    ) -> ConversationDocument:
        cleaned = None if workspace is None else str(workspace).strip() or None
        if cleaned is not None and len(cleaned) > 2048:
            raise ValueError("Workspace path is too long.")
        with self._lock:
            current = self.load(conversation_id)
            updated = self._replace(current, workspace=cleaned, updated_at=_now())
            self._write(updated)
            return updated

    def set_pinned(self, conversation_id: str, pinned: bool) -> ConversationDocument:
        with self._lock:
            current = self.load(conversation_id)
            updated = self._replace(current, pinned=bool(pinned), updated_at=_now())
            self._write(updated)
            return updated

    def branch(self, conversation_id: str, through_message_count: int | None = None) -> ConversationDocument:
        with self._lock:
            source = self.load(conversation_id)
            count = len(source.messages) if through_message_count is None else int(through_message_count)
            if count < 0 or count > len(source.messages):
                raise ValueError("Invalid branch message count.")
            now = _now()
            branch = ConversationDocument(
                uuid4().hex, f"{source.title} (branch)"[:100], False,
                now, now, list(source.messages[:count]), source.workspace,
            )
            self._write(branch)
            return branch

    def search(
        self, query: str, *, limit: int = 100, offset: int = 0
    ) -> tuple[ConversationSummary, ...]:
        expression = self._fts_query(query)
        if not expression:
            return self.list(limit=limit, offset=offset)
        with self._lock, self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT c.* FROM conversations_fts f
                JOIN conversations c ON c.conversation_id=f.conversation_id
                WHERE conversations_fts MATCH ?
                ORDER BY c.pinned DESC, c.updated_at DESC, c.conversation_id DESC
                LIMIT ? OFFSET ?
                """,
                (expression, max(1, min(int(limit), 500)), max(0, int(offset))),
            ).fetchall()
        return tuple(self._summary_from_row(row) for row in rows)

    def sync(self, conversation_id: str) -> ConversationDocument:
        with self._lock:
            document = self.load(conversation_id)
            self._upsert_metadata(document)
            return document

    def delete(self, conversation_id: str) -> bool:
        with self._lock:
            path = self._path(conversation_id)
            if not path.is_file():
                return False
            attachment_paths = self._mark_delete_pending(conversation_id)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            self._delete_projection(conversation_id)
            if self._cleanup_attachment_paths(attachment_paths):
                self._clear_pending("conversation_delete", conversation_id)
            return True

    def _path(self, conversation_id: str) -> Path:
        cleaned = str(conversation_id).strip()
        if (
            not cleaned
            or len(cleaned) > 128
            or cleaned in {".", ".."}
            or "/" in cleaned
            or "\\" in cleaned
        ):
            raise ValueError("Invalid conversation id.")
        return self.root / f"{cleaned}.json"

    def _read_path(self, path: Path) -> ConversationDocument:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Conversation file must contain a JSON object.")
        messages = _clean_messages(payload.get("messages"))
        conversation_id = str(payload.get("conversation_id") or path.stem).strip()
        if not conversation_id:
            raise ValueError("Conversation id is missing.")
        updated_at = str(payload.get("updated_at") or _now())
        created_at = str(payload.get("created_at") or updated_at)
        raw_title = payload.get("title")
        title = " ".join(str(raw_title).split()).strip() if raw_title else ""
        if not title:
            title = _title_from(messages)
        return ConversationDocument(
            conversation_id=conversation_id,
            title=title[:100],
            pinned=bool(payload.get("pinned", False)),
            created_at=created_at,
            updated_at=updated_at,
            messages=messages,
            workspace=(str(payload.get("workspace")).strip() if payload.get("workspace") else None),
        )

    @staticmethod
    def _replace(document: ConversationDocument, **changes: Any) -> ConversationDocument:
        values = {
            "conversation_id": document.conversation_id,
            "title": document.title,
            "pinned": document.pinned,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
            "messages": document.messages,
            "workspace": document.workspace,
        }
        values.update(changes)
        return ConversationDocument(**values)

    def _write(self, document: ConversationDocument) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self._path(document.conversation_id)
        payload = {
            "schema_version": 2,
            "conversation_id": document.conversation_id,
            "title": document.title,
            "pinned": document.pinned,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
            "messages": _clean_messages(document.messages),
            "workspace": document.workspace,
        }
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.root, delete=False
        ) as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            temporary = Path(stream.name)
        try:
            self._mark_sync_pending(document.conversation_id)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        self._upsert_metadata(document)
        return destination

    def _mark_sync_pending(self, conversation_id: str) -> None:
        self._set_pending("conversation_sync", conversation_id, "{}")

    def _mark_delete_pending(self, conversation_id: str) -> tuple[Path, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT stored_path FROM attachments WHERE conversation_id=?",
                (conversation_id,),
            ).fetchall()
            paths = tuple(Path(str(row["stored_path"])) for row in rows)
            payload = json.dumps(
                {"attachment_paths": [str(item) for item in paths]},
                ensure_ascii=False,
            )
            connection.execute(
                """
                INSERT INTO platform_records(namespace, record_id, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, record_id) DO UPDATE SET
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                ("conversation_delete", conversation_id, payload, _now()),
            )
            connection.commit()
        return paths

    def _set_pending(self, namespace: str, conversation_id: str, payload: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO platform_records(namespace, record_id, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, record_id) DO UPDATE SET
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (namespace, conversation_id, payload, _now()),
            )
            connection.commit()

    def _clear_pending(self, namespace: str, conversation_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM platform_records WHERE namespace=? AND record_id=?",
                (namespace, conversation_id),
            )
            connection.commit()

    def _pending_records(self, namespace: str) -> tuple[tuple[str, str], ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT record_id, payload FROM platform_records
                WHERE namespace=? ORDER BY updated_at
                """,
                (namespace,),
            ).fetchall()
        return tuple((str(row["record_id"]), str(row["payload"])) for row in rows)

    def _reconcile_pending_syncs(self) -> None:
        for conversation_id, _payload in self._pending_records("conversation_sync"):
            try:
                path = self._path(conversation_id)
            except ValueError:
                self._clear_pending("conversation_sync", conversation_id)
                continue
            if not path.is_file():
                self._clear_pending("conversation_sync", conversation_id)
                continue
            try:
                document = self._read_path(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            self._upsert_metadata(document)

    def _reconcile_pending_deletes(self) -> None:
        for conversation_id, payload in self._pending_records("conversation_delete"):
            try:
                path = self._path(conversation_id)
            except ValueError:
                self._clear_pending("conversation_delete", conversation_id)
                continue
            if path.is_file():
                self._clear_pending("conversation_delete", conversation_id)
                continue
            try:
                data = json.loads(payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                data = {}
            raw_paths = data.get("attachment_paths", []) if isinstance(data, dict) else []
            attachment_paths = tuple(Path(str(item)) for item in raw_paths if str(item).strip())
            self._delete_projection(conversation_id)
            if self._cleanup_attachment_paths(attachment_paths):
                self._clear_pending("conversation_delete", conversation_id)

    def _delete_projection(self, conversation_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM attachments WHERE conversation_id=?",
                (conversation_id,),
            )
            connection.execute(
                "DELETE FROM conversations_fts WHERE conversation_id=?",
                (conversation_id,),
            )
            connection.execute(
                "DELETE FROM conversations WHERE conversation_id=?",
                (conversation_id,),
            )
            connection.commit()

    @staticmethod
    def _cleanup_attachment_paths(paths: tuple[Path, ...]) -> bool:
        complete = True
        for attachment_path in paths:
            try:
                attachment_path.unlink(missing_ok=True)
                parent = attachment_path.parent
                if parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                complete = False
        return complete

    def _backfill_once(self) -> None:
        marker = "conversation_json_backfill_v1"
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM platform_records WHERE namespace=? AND record_id=?",
                ("migration", marker),
            ).fetchone()
        if existing is not None:
            return
        if self.root.is_dir():
            for path in self.root.glob("*.json"):
                try:
                    self._upsert_metadata(self._read_path(path))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO platform_records(namespace, record_id, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, record_id) DO UPDATE SET
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                ("migration", marker, "{}", _now()),
            )
            connection.commit()

    def _upsert_metadata(self, document: ConversationDocument) -> None:
        summary = document.summary()
        message_text = "\n".join(item["content"] for item in document.messages)
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO conversations(
                    conversation_id, title, pinned, workspace,
                    created_at, updated_at, preview
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    title=excluded.title, pinned=excluded.pinned,
                    workspace=excluded.workspace, created_at=excluded.created_at,
                    updated_at=excluded.updated_at, preview=excluded.preview
                """,
                (
                    summary.conversation_id, summary.title, int(summary.pinned),
                    summary.workspace, summary.created_at, summary.updated_at, summary.preview,
                ),
            )
            connection.execute(
                "DELETE FROM conversations_fts WHERE conversation_id=?",
                (summary.conversation_id,),
            )
            connection.execute(
                """
                INSERT INTO conversations_fts(conversation_id, title, preview, message_text)
                VALUES (?, ?, ?, ?)
                """,
                (summary.conversation_id, summary.title, summary.preview, message_text),
            )
            connection.execute(
                "DELETE FROM platform_records WHERE namespace=? AND record_id=?",
                ("conversation_sync", summary.conversation_id),
            )
            connection.commit()

    @staticmethod
    def _summary_from_row(row: Any) -> ConversationSummary:
        return ConversationSummary(
            conversation_id=str(row["conversation_id"]),
            title=str(row["title"]),
            pinned=bool(row["pinned"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            preview=str(row["preview"]),
            workspace=None if row["workspace"] is None else str(row["workspace"]),
        )

    @staticmethod
    def _fts_query(text: str) -> str:
        words = re.findall(r"[\w-]+", str(text), flags=re.UNICODE)
        return " AND ".join(f'"{word}"' for word in words)
