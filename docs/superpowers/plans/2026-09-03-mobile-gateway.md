# ChatMPD Mobile Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an authenticated installable phone client that uses Vader-hosted ChatMPD while keeping model/media backends private.

**Architecture:** Add a token/pairing store, a dependency-free HTTP gateway, embedded PWA assets, and desktop/CLI lifecycle hooks. The gateway calls an injected ChatMPD command handler and never proxies llama.cpp or ComfyUI.

**Tech Stack:** Python 3.11+ standard library, HTML/CSS/JavaScript PWA, unittest.

**Spec:** `docs/superpowers/specs/2026-09-03-mobile-gateway-design.md`

## Global Constraints

- Do not modify Windows Firewall or other security controls automatically.
- Keep llama.cpp and ComfyUI loopback-only.
- Persist only token digests, never bearer tokens or pairing codes.
- Bound JSON request bodies and reject malformed or unsupported content.
- Preserve the existing critical-action gate and model scheduler.

---

### Task 1: Pairing and device credentials

**Files:** Create `chatmpd/mobile_auth.py`; test `tests/test_mobile_auth.py`.

- [ ] Write failing tests for one-time codes, expiry, token hashing, validation, and revocation.
- [ ] Run `python -m unittest tests.test_mobile_auth -v` and confirm failure for missing implementation.
- [ ] Implement credential persistence with atomic local JSON writes and constant-time digest comparison.
- [ ] Re-run mobile-auth tests.

### Task 2: Authenticated HTTP gateway

**Files:** Create `chatmpd/mobile_gateway.py`; test `tests/test_mobile_gateway.py`.

- [ ] Write failing tests for health, pairing, bearer authentication, request-size bounds, security headers, and command dispatch.
- [ ] Implement a `ThreadingHTTPServer` gateway with only the documented routes.
- [ ] Serve PWA HTML and manifest from in-package constants/assets and disallow directory/file browsing.
- [ ] Re-run gateway and auth tests.

### Task 3: Application lifecycle and operator controls

**Files:** Modify `chatmpd/cli.py`, `chatmpd/app.py`; test CLI/app behavior.

- [ ] Add a `mobile` CLI command that prints the pairing URL/code and supports explicit LAN binding.
- [ ] Add lifecycle hooks usable by the desktop UI without changing firewall settings.
- [ ] Ensure owned gateway/model processes stop cleanly.
- [ ] Run targeted CLI/app/mobile tests.

### Task 4: Mobile UX and live verification

**Files:** Package mobile HTML/JS/CSS with the gateway; update `README.md` after behavior is verified.

- [ ] Add tests that the served client references the pairing and command APIs and is installable as a PWA.
- [ ] Run the full unit suite.
- [ ] Run a live loopback gateway smoke test with a temporary harmless command handler.
- [ ] Detect Vader's LAN address and report the phone URL without changing firewall rules.
- [ ] Include the gateway in the final PyInstaller build and desktop launcher work.
