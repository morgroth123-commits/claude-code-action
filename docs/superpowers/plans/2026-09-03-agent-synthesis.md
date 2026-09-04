# ChatMPD Agent Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ChatMPD a distinctive local assistant that combines proven agent behaviors from Vader's installed AI systems while preserving ChatMPD's offline, reversible, verification-first design.

**Architecture:** Put shared original behavior rules in a small doctrine module, then consume them from normal chat and coding-agent prompts. Add one plain-language front door that routes each request to the right capability without exposing backend complexity. Expand the deterministic engine with bounded search and surgical editing, then expose coding, media, system, ESO/Minion, Vortex, and future specialist flows through the desktop application without weakening the critical-system gate.

**Tech Stack:** Python 3.11+, llama.cpp/OpenAI-compatible local endpoint, tkinter, unittest, WSL2 + bubblewrap, ESO/Minion local metadata.

**Spec:** `docs/superpowers/specs/2026-09-03-standalone-product-spec.md`

## Global Constraints

- Local-first and usable without paid APIs, tokens, or cloud inference.
- Preserve unrelated dirty-worktree changes and never use destructive Git reset/checkout behavior.
- Keep secret-path protections, bounded context, reversible writes, and fresh verification before success.
- Keep GPU disabled and process priority conservative while `eso64.exe` is running.
- ESO changes require backups and must refuse mutation while ESO or Minion is active.
- Synthesize behavior principles in original wording; do not embed copied vendor system prompts.

---
### Task 1: Original operating doctrine

**Files:**
- Create: `chatmpd/doctrine.py`
- Modify: `chatmpd/assistant.py`
- Modify: `chatmpd/local_model.py`
- Test: `tests/test_doctrine.py`

**Interfaces:**
- Produces: `general_assistant_prompt()`, `coding_agent_prompt(allowed_commands)`, `eso_specialist_prompt()`.

- [ ] Write tests proving the doctrine contains ChatMPD identity, autonomy, evidence, preservation, verification, and local/privacy rules.
- [ ] Run `python -m unittest tests.test_doctrine -v` and confirm the new module is missing.
- [ ] Implement original doctrine builders and replace duplicated prompt strings.
- [ ] Re-run doctrine, assistant, and local-model tests.

### Task 2: Bounded project search

**Files:**
- Modify: `chatmpd/local_model.py`
- Modify: `chatmpd/engine.py`
- Test: `tests/test_engine_safety.py`
- Test: `tests/test_local_model.py`

**Interfaces:**
- Produces tool `search_text(query, path='.', case_sensitive=False)` with bounded safe results.

- [ ] Add failing tests for safe search, secret exclusion, result bounds, and tool schema.
- [ ] Implement search without following links or reading protected/sensitive files.
- [ ] Persist only result metadata/hashes, not matched source text, in run logs.
- [ ] Run targeted engine/local-model tests.
### Task 3: Surgical text editing

**Files:**
- Modify: `chatmpd/local_model.py`
- Modify: `chatmpd/engine.py`
- Test: `tests/test_engine_safety.py`

**Interfaces:**
- Produces tool `replace_text(path, old_text, new_text, expected_replacements=1)`.

- [ ] Add failing tests for exact replacement counts, atomic backup, protected paths, and stale verification invalidation.
- [ ] Implement bounded exact replacement using the existing safe-path and backup machinery.
- [ ] Return concise edit metadata to the model and persist no source contents.
- [ ] Re-run targeted safety tests.

### Task 4: Desktop assistant integration

**Files:**
- Modify: `chatmpd/app.py`
- Modify: `chatmpd/gui.py`
- Modify: `tests/test_app.py`
- Modify: `tests/test_gui.py`

**Interfaces:**
- Consume: `DesktopAssistant.chat(text)` and `DesktopAssistant.run_task(workspace, task)`.
- Produce: user-selectable Chat and Agent workflows sharing one managed runtime.

- [ ] Add tests for chat mode, agent mode, conversation reset, and shutdown cleanup.
- [ ] Wire the GUI to a long-lived `DesktopAssistant` while preserving current task UI behavior.
- [ ] Keep task execution backgrounded and local chat history persisted locally.
- [ ] Run app/gui/assistant tests.
### Task 5: ESO specialist integration and final verification

**Files:**
- Modify: `chatmpd/assistant.py`
- Modify: `chatmpd/gui.py`
- Modify: `chatmpd/eso.py` only where live evidence requires it
- Test: `tests/test_assistant.py`
- Test: `tests/test_eso.py`
- Modify: `README.md`

**Interfaces:**
- Consume: `EsoAddonManager.scan()`, `repair_safe_issues()`, `check_updates()`.
- Produce: ESO scan/report workflow with model explanation grounded in local scan/log evidence.

- [ ] Add tests for ESO routing and read-only scan behavior.
- [ ] Surface ESO health and repair planning without automatically deleting addons.
- [ ] Run the full unit suite and live read-only ESO scan on Vader.
- [ ] Run local llama.cpp chat/task smoke tests.
- [ ] Build `ChatMPD.exe` with PyInstaller and smoke-test the executable without a console window.
- [ ] Review `git diff`, preserve unrelated changes, and only claim completion after all checks pass.
