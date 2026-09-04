# ChatMPD Extensible Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a functional local-first ChatMPD platform with extensible capabilities, durable memory/knowledge, model management, workflows/automation, recovery/security, multimodal adapters, prompt guidance, sanitized sharing, and the finished WebView2/mobile UI.

**Architecture:** Keep `ChatMPDOrchestrator` authoritative. Add focused service modules behind a unified `PlatformServices` container and expose them through the loopback Web API/UI. Optional hardware/tool integrations report health explicitly rather than silently falling back to paid cloud services.

**Tech Stack:** Python 3.14, stdlib SQLite/FTS5/TOML/HTTP/subprocess/zipfile/ctypes, pywebview 6.x, existing llama.cpp/ComfyUI/FFmpeg stack; optional pypdf/openpyxl/cryptography/pyautogui where required.

**Spec:** `docs/superpowers/specs/2026-09-03-extensible-platform-design.md`

## Global Constraints

- No ChatMPD subscription, token billing, artificial usage quota, or mandatory paid API.
- Preserve existing coding/ESO/Vortex/system/media/mobile safety boundaries.
- Conversations remain until explicit deletion.
- Never weaken Windows security controls automatically.
- Generic/shareable exports exclude chats, memories, credentials, tokens, machine secrets, and explicit-sex generation extensions.

---
### Task 1: Finish mobile/WebView2 release baseline

**Files:** Modify `chatmpd/mobile_gateway.py`, `chatmpd/web_service.py`, `chatmpd/web/app.js`, `chatmpd/web/index.html`, `chatmpd/web/app.css`; tests `tests/test_mobile_gateway.py`, `tests/test_web_service.py`, `tests/test_web_assets.py`.

**Produces:** desktop `/api/mobile/start|status|stop`, one-time setup URL/QR payload, mobile client-mode endpoint, token-aware shared frontend.

- [ ] Keep the current failing tests as RED evidence.
- [ ] Add mobile lifecycle ownership to `WebAppService` using `MobileGateway`, `DeviceCredentialStore`, and private LAN URL discovery.
- [ ] Serve `/api/client` publicly from the mobile gateway and authenticate all other mobile `/api/*` except pairing.
- [ ] Add `pairDevice()` and mobile auth header handling in shared JS; prefill `?pair=` and hide pairing UI after token exchange.
- [ ] Run `python -m unittest tests.test_mobile_gateway tests.test_web_service tests.test_web_assets -v` until green.
- [ ] Commit `feat: finish shared desktop and mobile client`.

### Task 2: Capability registry, skills, plugins, external tools

**Files:** Create `chatmpd/capabilities.py`, `chatmpd/extensions.py`, `chatmpd/external_tools.py`, `chatmpd/platform_paths.py`; tests `tests/test_capabilities.py`, `tests/test_extensions.py`, `tests/test_external_tools.py`.

**Produces:** `CapabilityDescriptor`, `CapabilityRegistry`, `ExtensionManager`, `ExternalToolRunner`.

- [ ] Write RED tests for built-in registration, TOML skill discovery, duplicate-ID rejection, disabled/broken health states, subprocess plugin JSON invocation, CLI invocation, HTTP adapter policy, and MCP stdio JSON-RPC framing.
- [ ] Implement manifest validation and managed extension roots under `%LOCALAPPDATA%\ChatMPD\extensions`.
- [ ] Implement subprocess-only plugins and explicit CLI/HTTP/MCP adapters with bounded timeouts/output.
- [ ] Run targeted tests and commit `feat: add extensible capability registry`.

### Task 3: Durable memory, knowledge, attachments, retrieval

**Files:** Create `chatmpd/platform_db.py`, `chatmpd/memory.py`, `chatmpd/knowledge.py`, `chatmpd/attachments.py`; tests `tests/test_memory.py`, `tests/test_knowledge.py`, `tests/test_attachments.py`.

**Produces:** `PlatformDatabase`, `MemoryStore`, `KnowledgeLibrary`, `AttachmentStore`.

- [ ] Write RED tests for memory CRUD/search/provenance, FTS knowledge retrieval, text/CSV/DOCX/PDF extraction, managed attachment upload, and restart persistence.
- [ ] Implement SQLite schema migrations and FTS5 indexes with atomic source metadata updates.
- [ ] Implement bounded extractors and optional dependency fallbacks that report unavailable formats clearly.
- [ ] Run targeted tests and commit `feat: add durable memory and local knowledge`.
### Task 4: Hardware profile, model manager, benchmark/evaluation lab

**Files:** Create `chatmpd/hardware.py`, `chatmpd/model_lab.py`; modify `chatmpd/model_registry.py`, `chatmpd/model_runtime.py`; tests `tests/test_hardware.py`, `tests/test_model_lab.py`.

**Produces:** `HardwareProfile`, `ModelInventory`, `ModelBenchmarkStore`, role recommendations and explicit overrides.

- [ ] Write RED tests for RAM/CPU/GPU parsing, model-tier recommendations, registry inventory, benchmark persistence/scoring, and override precedence.
- [ ] Implement Windows hardware discovery without changing system settings.
- [ ] Implement bounded local benchmark runner using injected providers so tests never load real models.
- [ ] Run targeted tests and commit `feat: add hardware aware model lab`.

### Task 5: Workflows, multi-agent coordinator, automation, activity timeline

**Files:** Create `chatmpd/workflows.py`, `chatmpd/agents.py`, `chatmpd/automation_engine.py`, `chatmpd/activity.py`; tests `tests/test_workflows.py`, `tests/test_agents.py`, `tests/test_automation_engine.py`.

**Produces:** persistent `WorkflowStore`, `AgentCoordinator`, `AutomationStore/Scheduler`, and `ActivityLog`.

- [ ] Write RED tests for save/replay workflow, independent worker fan-out/consolidation, interval/daily due calculations, conditional result matching, restart persistence, and bounded activity events.
- [ ] Implement orchestrator-backed workflows and temporary worker roles without exposing private chain-of-thought.
- [ ] Implement scheduler thread plus `run_due()` API suitable for a separate daemon CLI mode.
- [ ] Run targeted tests and commit `feat: add workflows agents and automation`.

### Task 6: Permissions, secrets, recovery, backup/export

**Files:** Create `chatmpd/permissions.py`, `chatmpd/secrets_vault.py`, `chatmpd/recovery.py`, `chatmpd/exporter.py`; tests `tests/test_permissions.py`, `tests/test_secrets_vault.py`, `tests/test_recovery.py`, `tests/test_exporter.py`.

**Produces:** `PermissionProfileStore`, DPAPI `SecretsVault`, `RecoveryCenter`, `.chatmpdpack` and sanitized shareable exporter.

- [ ] Write RED tests for safe/autonomous/custom decisions, ciphertext-at-rest, reversible snapshots, rollback, pack sanitization, and explicit-extension rejection.
- [ ] Implement DPAPI on Windows with injected cipher fallback only for tests.
- [ ] Implement zip manifests with strict include lists; never crawl user state implicitly.
- [ ] Run targeted tests and commit `feat: add permissions recovery and sharing`.
### Task 7: Prompt guide, packs, extension wizard, diagnostics/self-repair

**Files:** Create `chatmpd/prompts.py`, `chatmpd/packs.py`, `chatmpd/extension_wizard.py`, `chatmpd/platform_doctor.py`; create `chatmpd/builtin_packs/*.toml`; tests `tests/test_prompts.py`, `tests/test_packs.py`, `tests/test_extension_wizard.py`, `tests/test_platform_doctor.py`.

**Produces:** prompt templates/optimizer, installable capability packs, skill/plugin skeleton generator, platform-wide health report and safe repairs.

- [ ] Write RED tests for prompt structure/templates, pack install/uninstall, generated manifest validation, broken-extension diagnosis, managed-folder/index repair, and prohibition on security-control repair actions.
- [ ] Implement generic built-in packs for Developer, Research, Media, Modding, ESO, and Windows diagnostics.
- [ ] Implement safe repairs limited to ChatMPD-owned folders/indexes/configuration.
- [ ] Run targeted tests and commit `feat: add prompt packs wizard and doctor`.

### Task 8: Multimodal/local desktop adapters

**Files:** Create `chatmpd/voice.py`, `chatmpd/vision.py`, `chatmpd/desktop_control.py`; tests `tests/test_voice.py`, `tests/test_vision.py`, `tests/test_desktop_control.py`.

**Produces:** Windows-local TTS, optional local Whisper file transcription, screenshot capture/vision-capability routing, disabled-by-default bounded desktop actions.

- [ ] Write RED tests with injected processes/capture backends for TTS command construction, missing Whisper health, screenshot artifact creation, no-cloud vision failure, and permission-gated click/type actions.
- [ ] Implement adapters with explicit health and no silent remote fallback.
- [ ] Run targeted tests and commit `feat: add local multimodal adapters`.

### Task 9: Platform services API and modern manager UI

**Files:** Create `chatmpd/platform_services.py`; modify `chatmpd/defaults.py`, `chatmpd/web_service.py`, `chatmpd/web/index.html`, `chatmpd/web/app.css`, `chatmpd/web/app.js`; tests `tests/test_platform_services.py`, `tests/test_web_service.py`, `tests/test_web_assets.py`.

**Produces:** `/api/platform/*` endpoints and UI panels for Memory, Knowledge, Skills & Tools, Models, Workflows, Automations, Recovery, Prompt Guide, Diagnostics, and Export.

- [ ] Write RED endpoint/asset tests for every manager surface and safe JSON shapes.
- [ ] Assemble services in `build_default_platform_services()` and inject into `WebAppService`.
- [ ] Implement manager dialog/pane navigation using safe DOM `textContent` rendering only.
- [ ] Run targeted tests and commit `feat: expose platform services in modern UI`.
### Task 10: Packaging, shareable build, docs, and release installation

**Files:** Modify `chatmpd/app.py`, `ChatMPD.spec`, `pyproject.toml`, `README.md`, `docs/architecture.md`, `docs/most-effective-usage.md`; create `docs/prompt-guide.md`; tests packaging/branding/full suite.

**Produces:** packaged local executable, generic shareable bundle, persistent desktop shortcut, automation-daemon CLI mode, documented unlimited-local-use policy.

- [ ] Update packaging data/hidden imports for new modules/assets and only required runtime dependencies.
- [ ] Run `python -m unittest discover -s tests -v` and require zero failures/errors.
- [ ] Run `python -m chatmpd doctor` plus live non-destructive platform smokes; verify persistent memory after process restart.
- [ ] Build `python -m PyInstaller --clean --noconfirm ChatMPD.spec` and require exit code 0.
- [ ] Install to `%LOCALAPPDATA%\ChatMPD\bin\ChatMPD.exe`, create/repair Desktop `ChatMPD.lnk`, compare SHA-256 hashes, launch one WebView2 window, then close and confirm no owned runtime leaks.
- [ ] Produce a sanitized generic shareable bundle and inspect its archive manifest for private-state exclusions.
- [ ] Commit/tag only after all release gates pass; leave Windows security/firewall unchanged.
