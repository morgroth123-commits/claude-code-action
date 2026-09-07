# DB Implications of Assistant-First Redesign

**Date:** 2026-09-06
**Audience:** ChatGPT (UI / interaction layer) and the ChatMPD developer
**Purpose:** Cross-reference between the [assistant-first interaction spec](2026-09-06-assistant-first-interaction-design.md) and the [database performance review](../../../output/database-performance-review.md) so neither workstream produces designs the other can't support.

---

## Intersection map

Each row connects a design requirement from the interaction spec to a database finding from the performance review.

| Interaction spec requirement | DB finding | What ChatGPT needs to know |
|---|---|---|
| **Sidebar: recent/pinned chats, search** (§ Conversational UI) | **Priority 2** — `ConversationLibrary.list()` reads every JSON file | The sidebar *must not* call the current `list()` for every render. It needs a SQLite-backed metadata table. Work with the DB changes below. |
| **IntentPlanner** queries memory/knowledge (§ Intent and planning) | **Priority 1** — `memories` list has no index on `(pinned, updated_at)` | The planner will hit `MemoryStore.list()` on many turns. That query currently does a full table scan. Indexes are ready — just confirm the query shape before locking it in. |
| **Missing workspace → guided action** (§ Context resolution) | **Priority 1** — `platform_records` list queries need index | The planner needs project/workspace state. If that state lives in `platform_records`, the index must exist first. Decide: does workspace live in conversation metadata or `platform_records`? |
| **Attachment chips + upload routes** (§ Context resolution, Conversational UI) | **Additional improvements** — attachment lifecycle | Adding upload/list/delete routes is straightforward. But conversation deletion must also delete attachments. If the new UI makes attachment use common, the orphan problem becomes real quickly. Add conversation-deletion cleanup alongside the new routes. |
| **File attachment via composer** (§ Conversational UI) | **Existing is sound** — `idx_attachments_conversation` already covers list-by-conversation | No schema change needed for attachment listing. The index already matches `WHERE conversation_id=? ORDER BY created_at`. |
| **Conversational errors: plain-language + action button** (§ Status, errors, and recovery) | **Additional improvements** — `database is locked` retry | The new error layer must translate `sqlite3.OperationalError: database is locked` into "ChatMPD is busy, try again in a moment." Add a retry/backoff wrapper around `PlatformDatabase.connect()` so transient locks resolve automatically before the UI sees them. |
| **Status labels** (§ Status, errors, and recovery) | No direct DB dependency | Status labels are UI-only, but make sure the backend exposes them without triggering extra queries per tick. |
| **Automations remain functional** (§ Compatibility) | **Priority 3** — scheduler polls all automations every 15s | If the new UI surfaces automation status more prominently, the polling cost becomes user-visible. The `automations` table with `(enabled, next_run)` index is a prerequisite for any automation dashboard. |
| **Knowledge retrieval for context** (§ Context resolution) | **Priority 4** — FTS maintenance for source replacement | If the planner triggers knowledge searches more often, the FTS index is already fine. But if source replacement (re-ingestion) becomes more common through the new UI, the `UNINDEXED source_id` FTS delete problem will surface. |
| **Welcome suggestions** (§ Conversational UI) | No DB impact | Suggestions are static; no query cost. |

---

## Blocking dependencies

These DB changes should land **before** the corresponding UI work, or the UI will feel slow immediately:

1. **Conversation metadata table** — before the new sidebar ships.
2. **`platform_records(namespace, updated_at DESC)` index** — before IntentPlanner ships.
3. **`memories(pinned DESC, updated_at DESC)` index** — before IntentPlanner ships (if planner queries memory).

## Non-blocking but high-value

These can land in parallel or after the initial UI work:

4. **Attachment delete-on-conversation-delete** — alongside new attachment routes.
5. **`database is locked` retry** — alongside conversational error handling.
6. **`INSERT OR REPLACE` → UPSERT** — any time; no UI coupling.
7. **Automation dedicated table** — before any automation dashboard UI.

---

## Schema for the conversation metadata table

This is the most important new schema for the interaction redesign. The sidebar, search, and planner all need it.

```sql
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0, 1)),
    workspace TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    preview TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_conversations_list
    ON conversations(pinned DESC, updated_at DESC, conversation_id DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
    conversation_id UNINDEXED, title, preview, message_text
);
```

**Write path:** `ConversationLibrary._write()` already serializes all of these fields to JSON. Add a parallel upsert to the `conversations` table in the same `_write()` method. For FTS, insert message text at save time.

**Read path for sidebar:**
```sql
SELECT * FROM conversations
ORDER BY pinned DESC, updated_at DESC, conversation_id DESC
LIMIT ? OFFSET ?;
```
This replaces the current `list()` method's full-directory scan. `OFFSET` provides cursor pagination for the sidebar.

**Search path:**
```sql
SELECT c.* FROM conversations_fts f
JOIN conversations c ON c.conversation_id = f.conversation_id
WHERE conversations_fts MATCH ?
ORDER BY c.pinned DESC, c.updated_at DESC
LIMIT ?;
```
This replaces the current `search()` method's double-scan (list all + reopen each match).

**Backfill:** On first startup after migration, iterate existing JSON files and populate the new table. This is a one-time cost per user.

---

## Migration plan (recommended order)

| Step | What | Who | Blocks |
|---|---|---|---|
| 1 | Add all indexes from Priority 1 | DB work | Nothing |
| 2 | Add `conversations` table + FTS, backfill, update `ConversationLibrary` | DB work | UI sidebar, search |
| 3 | Replace `INSERT OR REPLACE` with UPSERT | DB work | Nothing |
| 4 | Add `database is locked` retry wrapper | DB work | Conversational error handling |
| 5 | Add attachment cleanup on conversation delete | DB work | Attachment routes |
| 6 | IntentPlanner can now query memory + conversations via SQL | UI work | — |
| 7 | Sidebar uses `conversations` table instead of file scan | UI work | Step 2 |
| 8 | Search uses `conversations_fts` instead of file scan | UI work | Step 2 |
| 9 | Composer attachment routes call existing `AttachmentStore` | UI work | Step 5 |
| 10 | Automation dedicated table + scheduler rewrite | DB work | Automation dashboard |

---

## What each assistant owns

**Desktop Commander (DB layer):**
- Schema changes, indexes, migrations
- `ConversationLibrary` storage backend rewrite
- `PlatformDatabase` connection retry
- `AttachmentStore` lifecycle fixes
- `AutomationStore` table normalization
- Knowledge FTS rework

**ChatGPT (UI layer):**
- IntentPlanner — but confirm query patterns with DB review before finalizing
- Sidebar — assume SQLite-backed metadata exists (steps 2 + 7 above)
- Composer attachments — assume `AttachmentStore` routes exist
- Conversational errors — assume `database is locked` is handled at DB layer (step 4)
- Status labels, welcome suggestions, confirmation model — no DB dependency

**Shared decision needed:**
- Does workspace state live in `conversations.workspace` (SQLite) or remain JSON-only?
- Does the IntentPlanner query memory every turn, or is memory pre-loaded once per conversation?
- Are knowledge search results cached per-turn or re-queried?