# Vader Performance Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a functional, evidence-based Performance Center for Vader with analysis, reversible optimization profiles, adaptive game/AI behavior, history, and Control Center integration.

**Architecture:** `chatmpd.performance` owns probes, scoring, persisted reports, power-plan changes, and adaptive state. `PlatformServices` exposes one instance to the existing loopback API/UI. Host policy remains authoritative; only ChatMPD-owned/reversible optimizations run automatically.

**Tech Stack:** Python standard library, Windows `powercfg`, optional `nvidia-smi`, existing SQLite platform database, existing HTML/CSS/JS WebView2 Control Center.

**Spec:** `docs/superpowers/specs/2026-09-04-vader-performance-center-design.md`

## Global Constraints

- No new mandatory third-party runtime dependency.
- Analyze-only never mutates host state.
- Security, boot, firmware, disk, account, credential, or permission changes remain confirmation-gated.
- Never kill unrelated user processes or use realtime priority.
- Every applied optimization must be reversible and logged.

---### Task 1: Analyzer and scoring

**Files:**
- Create: `chatmpd/performance.py`
- Test: `tests/test_performance.py`

**Interfaces:**
- Produces: `PerformanceAnalyzer.analyze() -> PerformanceReport`
- Produces: `PerformanceStore.save(report)` and `PerformanceStore.list()`

- [ ] Write failing tests using injected CPU/memory/GPU/process/power probes. Assert 0-100 scores, deterministic bottleneck selection, bounded process list, and graceful missing GPU telemetry.
- [ ] Run `python -m unittest tests.test_performance -v` and verify RED.
- [ ] Implement immutable report/finding dataclasses, bounded probes, scoring, and SQLite-backed report persistence.
- [ ] Run the targeted tests and verify GREEN.
- [ ] Commit analyzer/scoring.

### Task 2: Reversible optimizer and adaptive controller

**Files:**
- Modify: `chatmpd/performance.py`
- Test: `tests/test_performance.py`

**Interfaces:**
- Produces: `VaderOptimizer.apply(mode: str) -> OptimizationResult`
- Produces: `VaderOptimizer.restore() -> OptimizationResult`
- Produces: `AdaptivePerformanceController.tick() -> str`

- [ ] Add failing tests proving Analyze-only performs zero writes, Gaming/AI/Balanced use only approved reversible actions, baseline power plan is captured/restored, and adaptive mode changes only on workload transitions.
- [ ] Run targeted tests and verify RED.
- [ ] Implement `powercfg` runner injection, policy checks, persisted optimizer state, activity evidence, and adaptive transitions.
- [ ] Run targeted tests and verify GREEN.
- [ ] Commit optimizer/adaptive controller.### Task 3: Platform/API integration

**Files:**
- Modify: `chatmpd/platform_services.py`
- Modify: `chatmpd/web_service.py`
- Test: `tests/test_platform_services.py`
- Test: `tests/test_web_platform.py`

**Interfaces:**
- Adds: `PlatformServices.performance`
- Adds: `GET /api/platform/performance`
- Adds: `POST /api/platform/performance/analyze|apply|restore|adaptive`

- [ ] Write failing service/API tests for summary, analyze, history, apply, restore, and adaptive settings.
- [ ] Run targeted tests and verify RED.
- [ ] Construct the analyzer/optimizer from existing platform services and add bounded loopback routes with explicit mode validation.
- [ ] Run targeted tests and verify GREEN.
- [ ] Commit platform/API integration.

### Task 4: Control Center Performance UI

**Files:**
- Modify: `chatmpd/web/index.html`
- Modify: `chatmpd/web/app.css`
- Modify: `chatmpd/web/app.js`
- Test: `tests/test_control_center_assets.py`

- [ ] Add failing asset tests for a `performance` Control Center section and safe API actions.
- [ ] Run the asset tests and verify RED.
- [ ] Add score cards, bottleneck/findings, process contention, Analyze, Balanced, Gaming, AI, Adaptive, Restore, and history controls using DOM-safe rendering only.
- [ ] Run asset/API/UI tests and verify GREEN.
- [ ] Commit UI integration.### Task 5: Documentation, live Vader verification, and release

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/most-effective-usage.md`

- [ ] Document Performance Center modes, adaptive behavior, safe boundaries, and restore semantics.
- [ ] Run `python -m unittest discover -s tests -v` and require a clean full-suite pass.
- [ ] Run a live Analyze-only Vader smoke and record CPU/RAM/GPU/storage/process/power evidence without mutations.
- [ ] Apply one reversible profile only if it requires no critical/security change, verify the resulting active plan/state, then restore the exact original state.
- [ ] Run source WebView2/mobile/model smokes and confirm no owned llama.cpp/ComfyUI leak.
- [ ] Build with `powershell -ExecutionPolicy Bypass -File scripts\build-windows.ps1`.
- [ ] Smoke-test the packaged executable, install it to the existing ChatMPD local-app path, recreate/verify the desktop shortcut, compute SHA-256, and confirm clean shutdown.
- [ ] Create and inspect the sanitized generic shareable package; verify it excludes private conversations, memory, credentials, tokens, and recovery state.
- [ ] Commit and tag the verified release state.