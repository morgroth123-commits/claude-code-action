# Most Effective Use of ChatMPD

ChatMPD is a local-first general assistant, not a coding-only task runner. The normal interface is the modern `ChatMPD.exe` conversation window. Ask in ordinary language; the router chooses reasoning, verified coding, system/ESO/Vortex specialists, media, skills, plugins, or external tools underneath one conversation.

## Start here

1. Open ChatMPD from the desktop shortcut.
2. Ask what you want in normal language.
3. Choose a project folder only for coding/project work.
4. Use the sidebar for persistent conversation history; **New chat does not delete old chats**.
5. Open **Control Center** for Memory, Knowledge, Skills & Tools, Models, Workflows, Automations, Recovery, Prompt Guide, Diagnostics, and Sharing.

All default inference remains local. ChatMPD itself has no per-token charge, subscription, artificial daily quota, or mandatory paid API. Hardware/model context limits still exist, and long conversations use persisted history plus retrieval rather than product metering.

## Persistent memory and knowledge

Conversation transcripts persist locally until you explicitly delete them. Opening an old chat reloads that conversation into the model context.

Durable memory is separate from chat history. Say `Remember that ...` for a fact or preference you want available across conversations. Review or delete durable memories in Control Center → Memory.

Use Control Center → Knowledge to index local text, Markdown, code, CSV/JSON, PDF, DOCX, and XLSX files. Relevant memory and knowledge are retrieved into the model's system context for the current request without being duplicated into the visible transcript.
## Skills, plugins, tools, and packs

Control Center → Skills & Tools lists built-in capabilities, portable Markdown/TOML skills, bounded subprocess plugins, CLI adapters, HTTP adapters, MCP stdio tools, and remote Streamable HTTP MCP tools. Extensions declare their permissions/risk/health and remain separate from ChatMPD's core process by default.

Capability packs group related functions such as Developer, Research, Media, Modding, ESO, and Windows diagnostics. The extension wizard can create a new skill skeleton from a name, purpose, and capability id; the generated skill still inherits ChatMPD's permission and verification boundaries.

Civitai is available in Skills & Tools as a remote MCP catalog. Browse/search tools work anonymously. Save an optional Civitai API key only through the protected connector control; posting, reacting, messaging, moderation, and other write actions remain explicit-confirmation operations.

For ESO, ChatMPD treats the public ESOUI catalog as the canonical discovery source and Minion's local state as installed-addon evidence. It does not impersonate Minion's private API. For Vortex/modding, Nexus Mods is the canonical repository source; public data works without an account while authenticated API features are optional.

## Models, LM Studio, and Bionic

ChatMPD discovers local GGUF models, records benchmark results, and can persist role overrides. Vader's proven llama.cpp role manager remains the primary runtime for reasoning/coding.

LM Studio is supported as an additional local OpenAI-compatible backend/management surface. If a normal LM Studio installation is not present, ChatMPD can detect the LM Studio runtime bundled with Bionic. Bionic is exposed as an optional companion launcher; ChatMPD does not enable Bionic cloud/credit usage on your behalf.

## Workflows and automations

Save a successful command as a Workflow when you want to replay it later. Workflows retain the natural-language command and optional project folder.

Automations store recurring or conditional local commands with a minimum one-minute interval. They remain inspectable and can be enabled, disabled, or deleted. Use clear conditions for watches so a recurring check does not create unnecessary noise.
## Coding and verification

Coding remains intentionally stricter than ordinary chat. ChatMPD profiles the selected Python project, limits reads/search/writes to the workspace, backs up eligible existing files, and permits only one pre-approved verification command. Verification runs against a filtered WSL/bubblewrap snapshot with networking disabled.

A coding task cannot report success until the required check passes after the most recent write. The result surface exposes changed files and verification evidence. Do not interpret a passing test as proof of every possible behavior; keep normal source control and backups.

## Mobile

Use **Connect phone** in the sidebar. Start mobile access, then use **Copy setup link**, QR, or the separate address/code buttons. The setup code is short-lived and one-time; the durable device credential is issued only after pairing.

The phone is a thin client—Vader performs the inference and tool work. llama.cpp and ComfyUI remain loopback-only. ChatMPD does not open Windows Firewall automatically. Use the LAN gateway only on a trusted private network; use a private overlay for remote access rather than a public port forward.

## Prompting

For complex work use **Goal → Context → Constraints → Desired result → Verification**. The integrated Prompt Guide can build this format, but ordinary language remains the default. See [Prompt Guide](prompt-guide.md) for practical templates.

## Recovery and diagnostics

Control Center → Recovery lists managed snapshots and requires explicit confirmation before rollback. Control Center → Diagnostics runs platform health checks and offers only repairs to ChatMPD-owned folders, indexes, and configuration—it does not weaken Windows security controls.
## Sharing

The generic sharing format is `.chatmpdpack`. Exports use an explicit include list and automatically reject private ChatMPD state such as conversations, durable memory, credentials, tokens, authentication state, recovery data, and explicit-sex extensions.

A recipient gets a generic ChatMPD by default and can then add models, skills, plugins, tools, workflows, packs, themes, or your curated shareable extensions. Large model/media weights remain external and retain their own licenses.

## Performance while playing ESO

When `eso64.exe` is detected, ChatMPD keeps the language runtime in the existing CPU-safe/idle-priority mode and refuses to start GPU media generation. Close ESO for maximum model/media performance. ESO and Minion also block addon mutations that could race their files.

## Important boundaries

Ordinary reversible work can run autonomously. Critical-impact actions—boot/firmware, disks/partitions, security controls, credentials, accounts/permissions, and similarly destructive system changes—still require explicit approval. Desktop control is disabled by default.

Local voice TTS is available through Windows. Whisper transcription and visual understanding are local-only optional adapters: when a required local model/runtime is missing, ChatMPD reports that state instead of silently sending the data to a cloud service.

## Keyboard note

In the modern WebView conversation composer, **Enter sends** and **Shift+Enter adds a new line**. The retained legacy/source project-runner interface uses **Ctrl+Enter** to start its permitted task; this shortcut remains documented for compatibility and troubleshooting.

## Credentials

Never put passwords, API keys, recovery phrases, private keys, or access tokens in ordinary prompts, reusable skills, or chat memory. Store optional connector credentials through ChatMPD's encrypted Secrets interface instead.

## Performance Center

Use **Control Center → Performance → Analyze** whenever you want a read-only snapshot of Vader. The dashboard shows overall/Gaming/AI/Balanced scores, the current bottleneck, GPU/VRAM telemetry when available, memory/storage headroom, power plan, workload state, and the top competing processes.

Use **Gaming** before a demanding game if you want ChatMPD to release its owned model runtime and maintain the high-performance profile. Use **AI / ChatMPD** when the machine is dedicated to local inference/media. **Balanced** returns to the captured baseline plan, and **Restore baseline** explicitly reapplies the original plan recorded before optimization.

Adaptive mode is useful when moving between ESO and ChatMPD work: it changes only on workload transitions and never terminates unrelated applications. Analyze-only is always non-mutating. Security, boot, firmware, disk, account, credential, and similarly critical changes are outside automatic performance optimization.
## Headless automation

Use `python -m chatmpd automations --once` to run all currently due automations and exit. Use `python -m chatmpd automations` for the local automation daemon while a console session is intended to stay active. The daemon uses the same local orchestrator, permissions, models, and evidence boundaries as the desktop app.

