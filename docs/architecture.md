# ChatMPD 0.3 architecture

ChatMPD is a local-first autonomous assistant with one plain-language front door. The WebView2 desktop client and paired mobile client use the same `ChatMPDOrchestrator`; specialist capabilities remain isolated so adding extensions or host tools does not weaken the verified coding boundary.

## High-level flow

```text
WebView2 desktop ─┐
                  ├─> WebAppService -> ChatMPDOrchestrator -> RequestRouter
Mobile thin client┘                         |
                                             +-> reasoning -> local model runtime
                                             +-> coding -> AgentEngine -> WSL/bubblewrap verification
                                             +-> ESO/Vortex/system/media specialists
                                             +-> PlatformServices -> memory/knowledge/extensions/workflows/etc.
```

`PlatformServices` owns the cross-cutting local platform: SQLite/FTS persistence, durable memory, knowledge indexing, attachments, capability registry, extensions, model lab, permissions, secrets, recovery, workflows, automations, activity evidence, prompts/packs, diagnostics, LM Studio/Bionic discovery, mod sources, voice/vision, and sanitized export.

## Persistence and retrieval

Conversation JSON remains under `%LOCALAPPDATA%\ChatMPD\conversations` until explicit deletion. Platform state is stored in `%LOCALAPPDATA%\ChatMPD\platform\chatmpd.db` using SQLite plus FTS5. Durable memory and knowledge-source chunks are separate from chat transcripts.

Before a reasoning turn, relevant durable memories and indexed knowledge are retrieved and added to the transient system context. Retrieval text is not duplicated into the visible conversation. Explicit `Remember that ...` requests add a durable memory while the original chat message remains part of its conversation.
## Models and runtimes

`ModelRegistry` discovers local GGUF files and maps them to reasoning, coding, fast-worker, and embedding roles. `ModelBenchmarkStore` records local quality/speed/memory observations and persistent role overrides. `ModelRuntimeManager` uses that selector and keeps at most one owned llama.cpp model active at a time.

LM Studio support is additive. `LMStudioIntegration` discovers a normal `lms` CLI/installation and can fall back to the LM Studio runtime bundled with Bionic. `LMStudioProvider` speaks only to a loopback OpenAI-compatible endpoint. Bionic is treated as an optional local companion/launcher; ChatMPD does not automatically turn on credit-billed cloud inference.

## Extensions and tools

`CapabilityRegistry` is the searchable inventory for built-ins and extensions. `ExtensionManager` discovers portable TOML manifests and Markdown skill bodies. Plugins execute out-of-process; CLI, HTTP, MCP stdio, and Streamable HTTP MCP adapters have bounded inputs/outputs/timeouts. Network-backed adapters require explicit permission rather than silently replacing a local capability. Civitai is registered through its HTTPS Streamable HTTP MCP endpoint: read-only tools can run anonymously, while account/write tools require the encrypted Civitai key plus explicit confirmation.

Capability packs group related features without duplicating implementations. `ExtensionWizard` creates new skill/plugin skeletons that inherit ChatMPD permission and verification rules. Platform Doctor reports broken extensions and performs repairs only within ChatMPD-managed state.

## Workflows, agents, and automation

`WorkflowStore` persists reusable natural-language commands. `AgentCoordinator` can fan independent roles out to bounded workers and consolidate their visible results without storing private chain-of-thought. `AutomationStore` persists recurring/conditional commands and due times; scheduler/daemon execution calls back through the same orchestrator rather than bypassing routing or permissions.

`ActivityLog` stores compact evidence/status events only. It rejects private-reasoning event categories.
## Specialist boundaries

The coding engine remains project-only: bounded inventory/read/search/write/replace tools, protected paths, per-run backups, one exact approved verification argv, and an offline WSL/bubblewrap snapshot. A success response is rejected unless required verification passed after the last write.

ESO uses local manifests/settings/Minion evidence and the public ESOUI catalog. It does not impersonate Minion's private repository API and refuses mutation while ESO or Minion owns the relevant files. Vortex remains read-only for local inventory; Nexus Mods is the canonical repository adapter, with authenticated API functions optional.

Media uses hidden loopback ComfyUI plus Z-Image/LTX workflows and FFmpeg. GPU media startup is denied while ESO is running. Local voice/vision adapters never silently fall back to cloud processing. Desktop control is disabled by default and permission-gated.

## Permissions, recovery, and secrets

`PermissionProfileStore` layers Safe/Autonomous/custom profiles over the permanent critical-action gate. Even Autonomous cannot silently cross boot/firmware, disks/partitions, Windows security controls, credentials, accounts/permissions, or similarly destructive boundaries.

`RecoveryCenter` creates integrity-checked managed file snapshots and requires explicit confirmation before rollback. `SecretsVault` uses Windows DPAPI for optional connector credentials. Secrets are stored outside ordinary chats/memory and shareable exports.

## UI, mobile, and sharing

The desktop shell is HTML/CSS/JS rendered in a native Edge WebView2 window. The main view stays conversation-first; Control Center surfaces platform management without exposing backend node graphs or raw model flags. Desktop APIs bind to loopback only.

The mobile gateway serves the same frontend over a private network. Pairing uses a short-lived one-time code; only a token digest persists on Vader. Raw llama.cpp/LM Studio/ComfyUI endpoints are never exposed by the mobile gateway.

`.chatmpdpack` export uses explicit include lists. Generic sharing excludes conversations, durable memory, credentials/tokens, authentication state, recovery data, machine-private state, and explicit-sex extensions. Large models remain external.

## Performance Center

`chatmpd.performance` is the host-performance subsystem. `PerformanceAnalyzer` collects bounded read-only Windows evidence plus optional `nvidia-smi` telemetry, normalizes it into Gaming/AI/Balanced/overall scores, persists reports, and identifies the lowest-headroom component without inventing missing telemetry.

`VaderOptimizer` owns reversible profile changes. Balanced selects the Windows Balanced scheme; Gaming and AI select High Performance while preserving the exact pre-optimization baseline for Restore. It captures the original power plan before the first mutation, routes host changes through `PermissionProfileStore`, logs activity evidence, and can restore the captured plan. Gaming mode also releases ChatMPD-owned model resources; AI mode favors local compute when no game is active; Analyze-only performs no writes.

`AdaptivePerformanceController` polls at low frequency and switches only on workload transitions. The Performance Center is exposed through `PlatformServices`, loopback `/api/platform/performance` routes, and the WebView2 Control Center.