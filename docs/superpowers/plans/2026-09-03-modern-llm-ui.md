# ChatMPD Modern LLM UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current Tk desktop console with a modern ChatGPT/Claude/Gemini-style WebView2 conversation UI while preserving ChatMPD's verified local backend and making phone pairing nearly one-click.

**Architecture:** Keep `ChatMPDOrchestrator` authoritative. Add a local conversation library, a loopback desktop web server/job controller, shared static frontend assets, and a `pywebview` Windows host. Reuse the same frontend assets from the paired mobile gateway so desktop and phone behavior stay aligned.

**Tech Stack:** Python 3.14, `pywebview` + Microsoft Edge WebView2, standard-library `ThreadingHTTPServer`, HTML/CSS/vanilla JavaScript, existing ChatMPD orchestrator, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-09-03-modern-llm-ui-design.md`

## Global Constraints

- Preserve model routing, coding sandbox, host policy, ESO/Vortex, ComfyUI/media and output locations.
- Desktop HTTP binds only to `127.0.0.1` on a dynamic port.
- Mobile remains opt-in, private-network-only, paired, and bearer-authenticated.
- llama.cpp and ComfyUI stay loopback-only and are never exposed directly.
- Existing conversation JSON must remain readable.
- Rich model output is rendered from escaped text; generated HTML/scripts are never executed.
- `MDRight-01.jpeg` remains the canonical ChatMPD identity.
- No Windows Firewall or Windows security setting changes.

---
### Task 1: Persistent conversation library

**Files:**
- Create: `chatmpd/conversation_library.py`
- Test: `tests/test_conversation_library.py`
- Modify: `chatmpd/assistant.py`

**Interfaces:**
- Produces `ConversationSummary`, `ConversationDocument`, and `ConversationLibrary`.
- `ConversationLibrary` supports `create`, `list`, `load`, `save_messages`, `rename`, `set_pinned`, `branch`, `delete`, and `search`.
- `DesktopAssistant` gains `load_conversation(conversation_id)` while keeping existing chat/task APIs.

- [ ] **Step 1: Write failing tests** for legacy JSON compatibility, chronological listing, generated titles, rename/pin/search, branching, deletion, and assistant conversation loading.
- [ ] **Step 2: Run** `python -m unittest tests.test_conversation_library tests.test_assistant -v` and confirm the new tests fail for missing behavior.
- [ ] **Step 3: Implement the library** using atomic JSON writes in `%LOCALAPPDATA%\ChatMPD\conversations`; never store raw model/tool secrets.
- [ ] **Step 4: Add assistant loading** by replacing `_conversation_id` and `_messages` from a validated library document under the existing lock.
- [ ] **Step 5: Re-run the targeted tests** and confirm all pass.
- [ ] **Step 6: Commit** `feat: add persistent conversation library`.

### Task 2: Asynchronous desktop job/API service

**Files:**
- Create: `chatmpd/web_service.py`
- Test: `tests/test_web_service.py`

**Interfaces:**
- Produces `WebAppService(orchestrator, conversations, assets_root)` with `start()`, `stop()`, `url`, and HTTP endpoints.
- `POST /api/jobs` returns a job id immediately; `GET /api/jobs/<id>` returns bounded state; `POST /api/jobs/<id>/cancel` requests safe cancellation.
- Conversation CRUD endpoints call `ConversationLibrary`; command completion persists user/assistant turns for every routed capability.
- [ ] **Step 1: Write failing API tests** for loopback binding, static assets, conversation CRUD, immediate job creation, job completion persistence, duplicate-work rejection, and bounded cancellation state.
- [ ] **Step 2: Run** `python -m unittest tests.test_web_service -v` and verify RED.
- [ ] **Step 3: Implement the loopback service** with `ThreadingHTTPServer`; serve only known static files and JSON; cap request bodies and result payloads.
- [ ] **Step 4: Implement jobs** with one serialized worker compatible with the orchestrator's existing lock. Persist final assistant text plus structured result metadata into the active conversation.
- [ ] **Step 5: Implement cancellation** as a safe request flag; release chat runtime when possible and otherwise stop only at supported boundaries. Never mark a cancelled job successful.
- [ ] **Step 6: Run targeted API tests** until green.
- [ ] **Step 7: Commit** `feat: add asynchronous desktop web service`.

### Task 3: Shared modern frontend

**Files:**
- Create: `chatmpd/web/index.html`
- Create: `chatmpd/web/app.css`
- Create: `chatmpd/web/app.js`
- Test: `tests/test_web_assets.py`

**Interfaces:**
- Frontend consumes the Task 2 JSON API and the existing paired mobile API shape.
- DOM rendering functions accept plain text/structured JSON only and build nodes with `textContent`; they do not inject model HTML.

- [ ] **Step 1: Write failing asset tests** asserting semantic landmarks, sidebar/new-chat/search controls, transcript, composer, result/artifact pane, theme support, keyboard hooks, mobile breakpoint, and safe rendering helpers.
- [ ] **Step 2: Run** `python -m unittest tests.test_web_assets -v` and verify RED.
- [ ] **Step 3: Build the HTML shell** with sidebar, quiet top bar, transcript, floating composer, status region, dialogs, mobile panel, and artifact pane.
- [ ] **Step 4: Build CSS** for dark/light/system themes, WCAG-AA text contrast, responsive sidebar overlay, code blocks, result cards, media previews, focus states, reduced motion, and modern LLM spacing.
- [ ] **Step 5: Build JavaScript** for conversation history/search/rename/pin/branch/delete, Enter/Shift+Enter behavior, job polling/progress, cancel, result cards, copy controls, and artifact pane.
- [ ] **Step 6: Run asset tests** and inspect the served UI in a browser/WebView at desktop and narrow widths.
- [ ] **Step 7: Commit** `feat: add modern shared conversation frontend`.
### Task 4: Native WebView2 desktop host

**Files:**
- Create: `chatmpd/webview_host.py`
- Modify: `chatmpd/app.py`
- Modify: `pyproject.toml`
- Modify: `ChatMPD.spec`
- Test: `tests/test_webview_host.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Produces `launch_webview(orchestrator)` which starts `WebAppService`, creates one native `pywebview` window, applies ChatMPD title/icon behavior, and guarantees service/orchestrator cleanup.
- Default no-argument app launch changes from Tk `launch_universal_gui` to `launch_webview`; Tk remains available only as an explicit development fallback.

- [ ] **Step 1: Write failing host/dispatch tests** with injected fake webview/service objects proving one window, correct title/URL, cleanup on close/error, and default dispatch to WebView.
- [ ] **Step 2: Run** `python -m unittest tests.test_webview_host tests.test_app -v` and verify RED.
- [ ] **Step 3: Add `pywebview` dependency** with a bounded supported version range and implement the host without exposing a Python JS bridge.
- [ ] **Step 4: Update PyInstaller data** to package `chatmpd/web/*` plus existing icon assets.
- [ ] **Step 5: Re-run targeted tests** and perform a source launch smoke using Edge WebView2 already installed on Vader.
- [ ] **Step 6: Commit** `feat: replace default desktop shell with WebView2`.

### Task 5: One-link mobile pairing and shared frontend

**Files:**
- Modify: `chatmpd/mobile_gateway.py`
- Create or Modify: `chatmpd/mobile_assets.py`
- Modify: `chatmpd/web/app.js`
- Modify: `chatmpd/web/index.html`
- Test: `tests/test_mobile_gateway.py`
- Test: `tests/test_mobile_auth.py`

**Interfaces:**
- Desktop mobile panel consumes `setup_url`, `address`, and `pairing_code` returned by the mobile session API.
- Setup URL contains only the temporary pairing code; successful exchange creates the durable token and invalidates the temporary value.

- [ ] **Step 1: Write failing tests** for setup URL construction, URL query prefill, single-use pairing, copyable address/code fields, and QR payload equality with the setup URL.
- [ ] **Step 2: Run mobile tests** and verify RED.
- [ ] **Step 3: Serve the shared frontend assets** from `MobileGateway` instead of the legacy embedded UI while retaining bearer auth for `/api/*`.
- [ ] **Step 4: Add setup-link handling** so `?pair=<temporary-code>` pre-fills pairing and never contains the long-lived token.
- [ ] **Step 5: Add copy-link/copy-address/copy-code controls and a locally generated QR representation**; keep manual pairing visible as fallback.
- [ ] **Step 6: Re-run mobile/web asset tests** and perform a paired-device API smoke.
- [ ] **Step 7: Commit** `feat: simplify mobile pairing flow`.
### Task 6: Structured results and artifact pane

**Files:**
- Modify: `chatmpd/web_service.py`
- Modify: `chatmpd/web/app.js`
- Modify: `chatmpd/web/app.css`
- Test: `tests/test_web_service.py`
- Test: `tests/test_web_assets.py`

**Interfaces:**
- Job completion payload exposes bounded `capability`, `message`, `details`, and normalized `artifacts[]` containing only known output paths/types.
- Frontend renders coding checks/changed files, ESO/Vortex/system summaries, image/video previews, and downloadable/openable result cards without raw JSON dumps.

- [ ] **Step 1: Add failing tests** for normalized image/video/file artifacts, coding verification presentation, specialist summaries, and rejection of arbitrary file paths.
- [ ] **Step 2: Run** the web service/asset tests and verify RED.
- [ ] **Step 3: Normalize result details** server-side and expose only bounded, explicit result metadata.
- [ ] **Step 4: Implement frontend result cards and artifact pane** with safe text rendering, copy/open actions, image/video preview, and collapsed operational details.
- [ ] **Step 5: Re-run targeted tests** and manually inspect real image/video and coding-result rendering.
- [ ] **Step 6: Commit** `feat: add rich result and artifact rendering`.

### Task 7: Release verification and replacement build

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `pyproject.toml` version if release version changes
- Rebuild: `dist/ChatMPD.exe`

- [ ] **Step 1: Update documentation** so default launch, conversation management, mobile copy-link/QR pairing, themes, and WebView2 recovery match the new product.
- [ ] **Step 2: Run the complete suite:** `python -m unittest discover -s tests -v`; expected result is zero failures/errors.
- [ ] **Step 3: Run live backend smokes** for reasoning, disposable verified coding, ESO/Vortex/system summaries, one real image, and one real video without altering active game/mod-manager state.
- [ ] **Step 4: Run source UI smokes** for new chat/history/search/rename/pin/branch/delete, light/dark, narrow window, keyboard-only navigation, mobile pairing, and cancel behavior.
- [ ] **Step 5: Build with PyInstaller** using `python -m PyInstaller --clean --noconfirm ChatMPD.spec`; require exit code 0.
- [ ] **Step 6: Launch the packaged executable** and verify one WebView2 ChatMPD window, correct icon/title, real chat response, and clean close with no owned ChatMPD/llama.cpp/ComfyUI processes left.
- [ ] **Step 7: Replace** `%LOCALAPPDATA%\ChatMPD\bin\ChatMPD.exe`, preserve the existing desktop shortcut target, compare SHA-256 hashes, and launch from the shortcut.
- [ ] **Step 8: Commit/tag the verified source** only after all release gates pass; leave Windows security settings unchanged.
