# ChatMPD Extensible Local Platform Design

**Date:** 2026-09-03
**Status:** Approved architecture, implementation authorized

## Objective

Turn ChatMPD into a locally operated, extensible assistant platform with persistent memory, skills, plugins, external tools, reusable workflows, automations, model management, multimodal helpers, recovery, prompt guidance, and sanitized sharing.

Normal ChatMPD operation must remain local-first with no subscription, per-token billing, artificial daily/monthly quota, or mandatory paid API. Model context/output limits are physical model constraints, not product quotas.

## Product invariants

- Existing verified coding, ESO, Vortex, system, media, mobile, and WebView2 architecture remains usable.
- Conversations persist until the user explicitly deletes them.
- Durable memory is separate from transcripts and is user-searchable/editable/deletable.
- Critical actions remain confirmation-gated by host policy.
- Windows security protections are never weakened automatically.
- Third-party paid/network services are optional, explicit, and disabled by default.
- Shareable builds contain no private chats, durable memories, credentials, tokens, or machine-specific secrets.
- Explicit-sex generation capabilities are excluded from shareable extension packs and generic builds.
## Capability registry and extensions

A single `CapabilityRegistry` inventories built-ins, skills, subprocess plugins, CLI tools, HTTP adapters, and MCP stdio servers. Each capability declares identifier, title, description, kind, version, enabled state, risk class, permissions, health, and invocation metadata.

Skills use a portable folder format with `skill.toml` plus Markdown instructions. Plugins execute out-of-process through a bounded JSON stdin/stdout contract instead of arbitrary in-process imports. External adapters are explicit and never inherit credentials implicitly.

Capability packs group compatible skills/tools/configuration for one-click install. Compatibility validation checks manifest schema, dependency availability, executable paths, duplicate IDs, requested permissions, and platform requirements before enabling an extension.

## Memory and knowledge

SQLite is the durable local store for long-term memories, knowledge-source metadata, automation definitions, workflow definitions, model benchmarks, and activity records. FTS5 provides dependency-free local retrieval; embedding providers are pluggable so the existing Nomic model can augment retrieval when an embedding runtime is available.

Knowledge ingestion supports text/code/JSON/Markdown, PDF, DOCX, XLSX/CSV, and uploaded conversation attachments using bounded extraction. Retrieval returns source/provenance with every hit.

## Models and routing

Model management discovers registry models, records size/role/quantization/path, captures host hardware, runs bounded benchmark prompts, and stores latency/quality/resource observations. Routing remains automatic but can consume benchmark scores and explicit role overrides.

A local evaluation lab compares installed models using the same prompt suite and never downloads or invokes a paid API silently.
## Workflows, agents, automation, and recovery

A `WorkflowStore` persists named sequences of ChatMPD requests and can replay them through the orchestrator. A coordinator can run bounded worker roles (research, coding, critique, verification, specialist) while exposing one consolidated conversation result.

Automations persist local schedules/conditions and execute through a scheduler engine. The UI-hosted scheduler runs while ChatMPD is open; a separate `automation-daemon` CLI mode enables unattended local execution without changing Windows Task Scheduler automatically.

Every platform-level mutation that ChatMPD owns records an activity event. Extension/configuration/workflow changes write recovery snapshots so the Recovery Center can describe and roll back supported reversible changes.

Permission profiles (`safe`, `autonomous`, and custom) map capability risk classes to allow/confirm/deny decisions. Credentials are isolated from chat/memory and protected with Windows DPAPI. Portable personal backups use password-derived authenticated encryption when the optional cryptography runtime is available.

## Multimodal and desktop helpers

Conversation attachments are uploaded into managed local storage and indexed when appropriate. Artifacts remain associated with conversations and can be previewed/opened from the artifact pane.

Voice support provides local Windows TTS and a speech-to-text adapter that uses a configured local Whisper/whisper.cpp executable when available. Vision support can capture/import screenshots and routes image understanding only to a registered local vision capability; absence is reported as an unavailable capability, never replaced by a cloud service silently.

Desktop control is an opt-in, permission-gated adapter for bounded mouse/keyboard/screenshot actions and is disabled by default.
## Prompting, diagnostics, and self-extension

The UI includes a Prompt Guide built around `Goal → Context → Constraints → Desired result → Verification`, with templates for research, coding, system work, media, files, diagnostics, and autonomous projects. Prompt improvement is optional and can use the active local reasoning model.

Doctor expands into platform diagnostics for models, extensions, databases, media, WebView2, mobile, and tool adapters. Safe self-repair may rebuild indexes, disable broken extensions, recreate missing managed folders, and clear disposable caches; it never alters Windows security controls automatically.

A skill/plugin creation wizard produces validated extension folders from a description and runs compatibility tests before installation. Self-extension may propose or build a missing local capability, but installation still obeys permission/risk policy and shareable-content restrictions.

## Sharing

Generic ChatMPD is the default distribution. `.chatmpdpack` archives contain selected skills, workflows, prompt templates, capability-pack manifests, and safe configuration only. Export performs path/secret/private-state sanitization and rejects disallowed explicit-generation packages.

A shareable application bundle contains the executable, setup guide, capability-pack catalog, and recommended-model manifest but not model weights unless redistribution is explicitly permitted. Hardware profiling recommends model tiers for the recipient machine.

Personal backup/export is a separate path from shareable export and may include conversations/memories only when explicitly selected.

## Acceptance

The release is functional when the full automated suite passes; the modern WebView2 UI launches; persistent chats survive restart; extension discovery/invocation works; memory/RAG works; workflows/automations execute; model/hardware inventory works; prompt guide and sharing export work; mobile copy-link pairing works; diagnostics expose degraded optional capabilities; and the packaged desktop build installs and launches cleanly.
