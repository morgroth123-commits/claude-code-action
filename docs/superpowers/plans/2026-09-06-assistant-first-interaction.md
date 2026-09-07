# ChatMPD Assistant-First Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ChatMPD understand and execute ordinary natural-language requests through one assistant-first interaction layer while simplifying the WebView UI for non-technical users.

**Architecture:** Add a schema-validated `IntentPlanner` in front of the existing deterministic `RequestRouter`; keep the router as fallback/policy guard. Extend orchestrator/web result metadata for missing-context and confirmation flows, wire the existing `AttachmentStore` into the conversation API, and simplify the shared WebView frontend around chat, attachments, contextual actions, and progressive disclosure.

**Tech Stack:** Python 3.14, existing local model provider/runtime, standard-library HTTP service, SQLite-backed platform services, HTML/CSS/vanilla JavaScript, pywebview/WebView2, unittest, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-09-06-assistant-first-interaction-design.md`
**Database dependency spec:** `docs/superpowers/specs/2026-09-06-database-implications-assistant-first.md`

## Global Constraints

- Preserve local-first inference and the existing verified coding sandbox.
- Preserve `RequestRouter` as deterministic fallback and policy guard.
- Planner output must be schema-validated and restricted to registered capabilities.
- Missing workspace/context must produce guided UI metadata rather than raw technical exceptions when recoverable.
- Attachments remain managed local copies using the existing `AttachmentStore`.
- Existing permission and permanent critical-action confirmation rules cannot be weakened.
- Do not expose raw chain-of-thought, stack traces, secrets, tool payloads, or backend policy objects in the default UI.
- Preserve existing conversations, memory, knowledge, mobile pairing/auth, extensions, model runtimes, ESO/Vortex/media handlers, and recovery data.
- No mandatory cloud/API/subscription/telemetry dependency.
- Preserve safe DOM rendering: no model-provided HTML injection.
- Preserve unrelated untracked files in the repository.

---

### Task 0: Database foundation required by assistant-first UI

**Files:**
- Modify: `chatmpd/platform_db.py`
- Modify: `chatmpd/conversation_library.py`
- Modify: `chatmpd/assistant.py`
- Modify: `chatmpd/webview_host.py`
- Modify: `chatmpd/attachments.py` as needed for conversation lifecycle cleanup
- Test: conversation/database/attachment integration tests

**Interfaces:**
- SQLite-backed conversation metadata/FTS becomes the sidebar/search projection while JSON remains the authoritative transcript body.
- `ConversationLibrary.list()` and `search()` stop scanning every transcript.
- Both `ConversationLibrary` and `ConversationStore` writes keep SQLite metadata synchronized.
- Workspace remains per-conversation and is mirrored in `conversations.workspace` plus JSON.
- Priority-1 DB indexes and transient lock handling land before IntentPlanner/sidebar work.

- [ ] **Step 1: Read the database dependency spec and performance review; write failing schema, backfill, synchronization, pagination/search, lock-retry, and attachment-cleanup tests.**
- [ ] **Step 2: Run the focused tests and verify RED.**
- [ ] **Step 3: Implement the Priority-1 indexes, one-time WAL setup/per-connection busy handling, SQLite conversation metadata + FTS, idempotent legacy JSON backfill, synchronized write paths, and conversation attachment cleanup.**
- [ ] **Step 4: Run focused GREEN tests plus `git diff --check`.**
- [ ] **Step 5: Commit as an independently reviewable DB foundation before Task 1.**

---
### Task 1: Add schema-validated intent planning with deterministic fallback

**Files:**
- Create: `chatmpd/intent.py`
- Modify: `chatmpd/router.py`
- Modify: `chatmpd/orchestrator.py`
- Test: `tests/test_intent.py`
- Test: `tests/test_router.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Produces `IntentPlan(capability, requires_workspace, confidence, reason, missing_context, suggested_action)`.
- Produces `IntentPlanner.plan(text, *, workspace=None, capabilities=()) -> IntentPlan`.
- `ChatMPDOrchestrator` accepts optional `intent_planner` and uses deterministic `RequestRouter` on planner failure/invalid output.

- [ ] **Step 1: Write failing planner schema tests**
  - Require unknown capability rejection.
  - Require confidence clamping/validation to `0.0 <= confidence <= 1.0`.
  - Require empty prompt rejection.
  - Require a semantically phrased coding request such as `Make the calculator stop returning the wrong total` to be routable by an injected planner without depending on old keyword tokens.
  - Require malformed planner output to fall back to `RequestRouter`.

- [ ] **Step 2: Run RED**
  Run:
  `.\.venv\Scripts\python.exe -m unittest tests.test_intent tests.test_router tests.test_orchestrator -v`
  Expected: import/missing-interface failures for `chatmpd.intent` and planner-aware orchestration.

- [ ] **Step 3: Implement `IntentPlan` and `IntentPlanner`**
  - Use an immutable dataclass.
  - Give the planner only the supported capability catalog.
  - Parse structured JSON from the reasoning provider; reject unknown fields/capabilities.
  - Keep planner prompt bounded and prohibit tool invention.
  - Return deterministic fallback on provider/JSON/schema failure.

- [ ] **Step 4: Integrate planner without weakening router behavior**
  - `ChatMPDOrchestrator` asks the planner first when configured.
  - If the planner is absent, fails, returns invalid data, or confidence is below the configured threshold, use `RequestRouter.classify`.
  - Existing router tests must continue to pass unchanged unless wording is intentionally improved.

- [ ] **Step 5: Run GREEN**
  Run:
  `.\.venv\Scripts\python.exe -m unittest tests.test_intent tests.test_router tests.test_orchestrator -v`
  Expected: all pass.

- [ ] **Step 6: Commit**
  `git add chatmpd/intent.py chatmpd/router.py chatmpd/orchestrator.py tests/test_intent.py tests/test_router.py tests/test_orchestrator.py`
  `git commit -m "feat: add assistant-first intent planning"`

---

### Task 2: Convert missing context and confirmations into structured conversational results

**Files:**
- Modify: `chatmpd/orchestrator.py`
- Modify: `chatmpd/permissions.py` only if a small presentation adapter is required
- Modify: `chatmpd/host_policy.py` only if stable action metadata is missing
- Test: `tests/test_orchestrator.py`
- Test: `tests/test_permissions.py`

**Interfaces:**
- Extend `CommandResult` with optional UI-safe metadata inside `details` without breaking `as_dict()`.
- Recoverable missing project returns `status="needs_context"`, `needs_context={"kind":"workspace",...}`, and `suggested_action="choose_workspace"`.
- Confirmation descriptors contain only user-safe labels and an opaque action token.

- [ ] **Step 1: Write failing orchestration tests**
  - Coding request without workspace returns a `CommandResult` instead of raising `ValueError`.
  - The result message explains that a project folder is needed.
  - The metadata exposes `needs_context.kind == "workspace"` and `suggested_action == "choose_workspace"`.
  - Existing critical permission decisions still require confirmation.

- [ ] **Step 2: Run RED**
  Run:
  `.\.venv\Scripts\python.exe -m unittest tests.test_orchestrator tests.test_permissions -v`
  Expected: missing-context test fails under current exception behavior.

- [ ] **Step 3: Implement recoverable context result**
  - Keep invalid filesystem paths and unrecoverable backend failures as failures.
  - Do not silently choose an arbitrary workspace.
  - Preserve existing coding verification details when a workspace exists.

- [ ] **Step 4: Add bounded confirmation presentation adapter if required**
  - Convert existing confirmation requirement into title/consequence/token/button labels.
  - Do not serialize internal policy objects to the frontend.

- [ ] **Step 5: Run GREEN and commit**
  Run:
  `.\.venv\Scripts\python.exe -m unittest tests.test_orchestrator tests.test_permissions -v`
  Commit:
  `git commit -am "feat: add conversational context and confirmation results"`

---

### Task 3: Expose existing managed attachments through the conversation API

**Files:**
- Modify: `chatmpd/web_service.py`
- Modify: `chatmpd/platform_services.py` if attachment service is not already exposed there
- Test: `tests/test_web_service.py`
- Test: `tests/test_attachment_upload.py`

**Interfaces:**
- `POST /api/conversations/<id>/attachments` accepts bounded JSON with base64 bytes, filename, and content type.
- `GET /api/conversations/<id>/attachments` lists managed records.
- `DELETE /api/conversations/<id>/attachments/<attachment_id>` deletes only an attachment belonging to that conversation.
- Job payload accepts `attachment_ids`.

- [ ] **Step 1: Write failing API tests**
  - Upload a small text attachment and verify managed persistence.
  - List returns id/name/type/size but not arbitrary raw filesystem access.
  - Deleting another conversation's attachment is rejected.
  - Oversize uploads return bounded user-safe errors.
  - Job creation rejects unknown attachment ids.

- [ ] **Step 2: Run RED**
  Run:
  `.\.venv\Scripts\python.exe -m unittest tests.test_attachment_upload tests.test_web_service -v`

- [ ] **Step 3: Implement attachment routes using `AttachmentStore`**
  - Reuse `import_bytes`, `list`, `get`, and `delete`.
  - Validate conversation ownership before delete/use.
  - Keep request size limits bounded; raise the web body cap only enough for the configured attachment ceiling or use a separate explicit upload ceiling.

- [ ] **Step 4: Add attachment context to jobs**
  - Persist attachment ids with the job request.
  - Build a bounded context summary for reasoning turns.
  - Coding requests may use attached text as context but may not write outside the selected workspace.

- [ ] **Step 5: Run GREEN and commit**
  Run:
  `.\.venv\Scripts\python.exe -m unittest tests.test_attachment_upload tests.test_web_service -v`
  Commit:
  `git add chatmpd/web_service.py chatmpd/platform_services.py tests/test_web_service.py tests/test_attachment_upload.py`
  `git commit -m "feat: add conversational attachment API"`

---

### Task 4: Make the WebView composer and transcript assistant-first

**Files:**
- Modify: `chatmpd/web/index.html`
- Modify: `chatmpd/web/app.js`
- Modify: `chatmpd/web/app.css`
- Test: `tests/test_web_assets.py`

**Interfaces:**
- Composer adds `attachment-button`, hidden file input, `attachment-list`, and drop target behavior.
- Missing-context results can invoke `chooseWorkspace()` from an inline action.
- Suggestions send ordinary text; they do not switch modes.

- [ ] **Step 1: Write failing asset tests**
  Require:
  - attachment button/input/list,
  - drag/drop handlers,
  - `uploadAttachments`,
  - `renderAttachmentChips`,
  - `renderSuggestedAction`,
  - `renderConfirmation`,
  - welcome suggestion buttons,
  - no `innerHTML`,
  - no raw capability IDs rendered as primary labels.

- [ ] **Step 2: Run RED**
  Run:
  `.\.venv\Scripts\python.exe -m unittest tests.test_web_assets -v`

- [ ] **Step 3: Simplify the shell**
  - Change Control Center label to `Settings`.
  - Move technical platform navigation under an `Advanced` disclosure.
  - Keep Memory, Personalization/Appearance, Mobile, and Recovery discoverable.
  - Replace welcome backend inventory prose with plain examples such as `Help me with this PC`, `Work on a project`, `Create an image`, and `Explain something`.

- [ ] **Step 4: Implement attachment UX**
  - Plus button opens file picker.
  - Drag/drop uploads files.
  - Chips show filename and remove button.
  - Send includes selected attachment ids.
  - Successful send retains uploaded records in the conversation but clears the pending-selection state.

- [ ] **Step 5: Implement inline recovery/confirmation cards**
  - `choose_workspace` action opens native folder picker.
  - Confirmation buttons submit only the opaque action token through a bounded endpoint or follow-up job payload.
  - Errors remain plain language.

- [ ] **Step 6: Improve transcript actions**
  - Keep Copy.
  - Add Retry for the last failed request where safe.
  - Add contextual artifact/open actions only when structured metadata exists.
  - Keep technical verification collapsed by default.

- [ ] **Step 7: Run GREEN and commit**
  Run:
  `.\.venv\Scripts\python.exe -m unittest tests.test_web_assets -v`
  Commit:
  `git add chatmpd/web/index.html chatmpd/web/app.js chatmpd/web/app.css tests/test_web_assets.py`
  `git commit -m "feat: simplify ChatMPD conversational UI"`

---

### Task 5: Add evidence-based job status and user-safe error recovery

**Files:**
- Modify: `chatmpd/web_service.py`
- Modify: `chatmpd/orchestrator.py`
- Modify: `chatmpd/web/app.js`
- Test: `tests/test_web_service.py`
- Test: `tests/test_web_assets.py`

**Interfaces:**
- `_Job` exposes optional `status_label`.
- Public status labels are selected from a bounded set and never contain hidden reasoning.
- Failed jobs expose a plain `message` plus optional `suggested_action`, not raw exception-class prefixes.

- [ ] **Step 1: Write failing tests**
  - Queued/running/completed/cancelled jobs expose sensible status labels.
  - Recoverable workspace problem completes as `needs_context`, not failed.
  - Backend errors are whitespace-normalized and bounded.
  - Raw traceback text is never returned.

- [ ] **Step 2: Run RED**
  Run:
  `.\.venv\Scripts\python.exe -m unittest tests.test_web_service tests.test_web_assets -v`

- [ ] **Step 3: Implement status/error presentation**
  - Keep operational event categories compact.
  - Do not fabricate percentages.
  - Preserve full technical evidence in existing local logs/recovery records rather than default chat text.

- [ ] **Step 4: Run GREEN and commit**
  `git add chatmpd/web_service.py chatmpd/orchestrator.py chatmpd/web/app.js tests/test_web_service.py tests/test_web_assets.py`
  `git commit -m "feat: add guided job status and recovery"`

---

### Task 6: Wire the planner into production application construction

**Files:**
- Modify: `chatmpd/app.py`
- Modify: `chatmpd/platform_services.py` as needed for capability catalog/context
- Modify: `chatmpd/doctrine.py`
- Test: `tests/test_app.py`
- Test: `tests/test_prompt_integration.py`
- Test: `tests/test_vertical_slice.py`

**Interfaces:**
- Production `ChatMPDOrchestrator` receives a configured `IntentPlanner`.
- Planner uses the same local reasoning runtime/model manager already owned by ChatMPD; it does not start a second permanent model runtime.
- General assistant prompt states that ordinary language is sufficient and tools/capabilities should be selected automatically.

- [ ] **Step 1: Write failing construction/integration tests**
  - Default app wiring creates planner-aware orchestrator.
  - Capability catalog includes chat/coding/system/performance/eso/vortex/media plus ready extension categories.
  - Existing vertical-slice routing still succeeds when planner is stubbed.

- [ ] **Step 2: Run RED**
  Run:
  `.\.venv\Scripts\python.exe -m unittest tests.test_app tests.test_prompt_integration tests.test_vertical_slice -v`

- [ ] **Step 3: Implement production wiring**
  - Share provider/runtime ownership safely.
  - Planner failures never prevent deterministic fallback.
  - Planner context is bounded and contains no secrets.

- [ ] **Step 4: Run GREEN and commit**
  `git add chatmpd/app.py chatmpd/platform_services.py chatmpd/doctrine.py tests/test_app.py tests/test_prompt_integration.py tests/test_vertical_slice.py`
  `git commit -m "feat: enable assistant-first planning by default"`

---

### Task 7: Documentation, version alignment, and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/most-effective-usage.md`
- Modify: `pyproject.toml` and package metadata only if version is advanced
- Verify: all production/test files
- Generate: `dist/ChatMPD.exe`

**Interfaces:**
- Documentation teaches ordinary-language use first and moves implementation terminology to advanced/reference sections.

- [ ] **Step 1: Update docs**
  - State that users normally just ask for the result they want.
  - Explain project selection only when project editing is requested.
  - Explain attachments and inline confirmations.
  - Remove guidance that implies users must know prompt formulas, model roles, or capability names for ordinary use.

- [ ] **Step 2: Run targeted regression suite**
  Run:
  `.\.venv\Scripts\python.exe -m unittest tests.test_intent tests.test_router tests.test_orchestrator tests.test_web_service tests.test_web_assets tests.test_attachment_upload tests.test_app tests.test_vertical_slice -v`

- [ ] **Step 3: Run full verification**
  Run:
  `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`
  `.\.venv\Scripts\python.exe -m compileall -q chatmpd chatmpd_launcher.py`
  `git diff --check`
  Expected: zero test failures/errors, compile exit 0, whitespace check clean.

- [ ] **Step 4: Run source UI smoke**
  Launch the source WebView and verify:
  - plain chat,
  - semantically phrased project request,
  - guided project selection,
  - attachment upload/remove/send,
  - Settings/Advanced disclosure,
  - light/dark,
  - stop/cancel,
  - one specialist request.

- [ ] **Step 5: Build**
  Run:
  `.\scripts\build-windows.ps1`
  Expected: PyInstaller succeeds and `dist\ChatMPD.exe` exists.

- [ ] **Step 6: Packaged smoke**
  Launch packaged executable and verify new chat, one local response, guided project action, and clean close.

- [ ] **Step 7: Run CodeRabbit**
  Verify/install/authenticate `coderabbit`, then run:
  `coderabbit review --agent -t uncommitted`
  or, if implementation commits are used and the release diff is committed:
  `coderabbit review --agent --base-commit 1515cc0`
  Resolve material critical/major issues with tests. Report any remaining issues exactly.

- [ ] **Step 8: Final repository evidence**
  Run:
  `git status --short`
  `git log --oneline --decorate -10`
  `Get-FileHash .\dist\ChatMPD.exe -Algorithm SHA256`
  Preserve unrelated pre-existing untracked files.
