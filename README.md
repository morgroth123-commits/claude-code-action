# ChatMPD 0.3.3

ChatMPD is a local-first autonomous Windows assistant with a modern WebView2 conversation UI, persistent chats and memory, extensible skills/plugins/tools, local model routing, verified coding, ESO/Vortex specialists, local media, mobile access, workflows/automation, and sanitized sharing.

The normal interface is `ChatMPD.exe`. Desktop and phone use the same orchestrator and local data. Default inference stays on the owner's machine and ChatMPD itself has no subscription, per-token billing, artificial usage quota, or mandatory paid API.

## Main capabilities

- Persistent conversation history; New Chat never erases earlier chats.
- Durable cross-chat memory plus local document/knowledge retrieval.
- Control Center for Memory, Knowledge, Skills & Tools, Models, Workflows, Automations, Recovery, Prompt Guide, Diagnostics, and Sharing.
- Skills from TOML + Markdown; bounded subprocess plugins; CLI, HTTP, MCP stdio, and remote Streamable HTTP MCP adapters.
- Capability packs and an extension wizard.
- Hardware-aware local model inventory, benchmarks, and role overrides.
- llama.cpp as Vader's proven primary runtime, plus LM Studio-compatible local integration and Bionic companion support.
- Hardened autonomous coding with workspace-only tools, backups, and fresh WSL/bubblewrap verification.
- ESO diagnostics/guarded repair using local Minion evidence and the public ESOUI catalog.
- Read-only Vortex inventory plus Nexus Mods repository integration with optional authenticated API features.
- Civitai platform MCP browsing is anonymous by default; optional account/write actions use a DPAPI-protected key and explicit confirmation.
- Z-Image and LTX-Video through hidden loopback ComfyUI; FFmpeg assembly.
- Local Windows TTS, optional local Whisper transcription, screenshots, local-only vision adapter, and disabled-by-default desktop control.
- One-time mobile pairing with Copy setup link, QR, address/code fallbacks, and revocable device credentials.
- Reusable workflows, recurring/conditional automation storage, evidence timeline, recovery snapshots, and sanitized `.chatmpdpack` export.
- Headless `chatmpd automations` mode for recurring local tasks when the desktop UI is not running.
## Vader model/media stack

| Role | Default |
| --- | --- |
| Reasoning | gpt-oss-20B MXFP4 via llama.cpp |
| Coding | Qwen2.5-Coder-7B-Instruct Q4_K_M |
| Fast worker | Qwen2.5-Coder-1.5B variants |
| Embeddings | Nomic Embed Text |
| Image | Z-Image-Turbo NVFP4 via ComfyUI |
| Video | LTX-Video 2B distilled FP8 via ComfyUI |
| Assembly | FFmpeg |

Compatible GGUF models are discovered rather than permanently hard-coded. The runtime keeps at most one role-selected llama.cpp model active. LM Studio is supported as an additional localhost OpenAI-compatible runtime/management surface; Bionic's bundled LM Studio runtime can be detected when present. Optional cloud/credit features are never enabled silently.

## One front door

Examples:

- `Remember that I prefer dark mode.`
- `Index C:\Docs\ESO-notes.pdf and use it when I ask about addons.`
- `Scan my ESO addons and prioritize compatibility problems without changing anything while Minion is running.`
- `Show me what Vortex is managing and use Nexus as the canonical mod repository.`
- `Fix the failing unit test in this project and finish only after verification passes.`
- `Create a ten-second cinematic video of a snowy forest.`
- `Save this as a workflow.`

Routing, memory retrieval, model/tool choice, specialist selection, and verification happen below the same conversation interface.
## Safety and recovery

Coding changes stay inside the selected project and use an exact approved verification command in an offline WSL/bubblewrap snapshot. Host-level critical actionsâ€”boot/firmware, disks/partitions, security controls, credentials, accounts/permissions, and similarly destructive changesâ€”remain confirmation gates. Windows Firewall/security settings are never silently weakened.

Recovery snapshots cover managed reversible file changes. The activity log stores visible evidence/status, not private chain-of-thought. Secrets for optional connectors are stored separately with Windows user protection rather than in prompts or ordinary memory.

## Mobile and sharing

Mobile access is a thin private-network client; Vader remains the compute host. llama.cpp and ComfyUI stay loopback-only. Remote access should use a private overlay rather than a public port-forward.

Generic `.chatmpdpack` exports use explicit include paths and exclude conversations, durable memory, credentials/tokens, authentication state, recovery data, and explicit-sex extensions. Large model/media files remain external and retain their own licenses.

## Documentation

- [Most Effective Usage](docs/most-effective-usage.md)
- [Prompt Guide](docs/prompt-guide.md)
- [Architecture](docs/architecture.md)
- [Windows setup](docs/setup-windows.md)
- [Security model](docs/security.md)
- [Troubleshooting and recovery](docs/troubleshooting.md)

## License

ChatMPD is licensed under the [MIT License](LICENSE). Third-party software, services, repositories, and models retain their own licenses and terms.

## Performance Center

Control Center â†’ **Performance** analyzes Vader without changing it, scores Gaming, AI, Balanced, and overall headroom, identifies only active bottlenecks, and shows bounded CPU/RAM/commit/pagefile/disk-queue/process-I/O/GPU/VRAM/power evidence. Reports are retained locally so optimizations can be compared against a before/after baseline.

Available modes are **Analyze only**, **Balanced**, **Gaming**, and **AI / ChatMPD**. Automatic changes are deliberately limited to reversible Windows power-plan selection and ChatMPD-owned runtime coordination. Adaptive mode can protect ESO when `eso64.exe` appears and restore the selected base mode after the game exits.

The analyzer also reports startup-load count, physical-disk health, and read-only Game Mode/HAGS state. Performance optimization never disables Windows security, changes Game Mode/HAGS, edits startup entries, changes BIOS/firmware/boot/disk settings, uses realtime priority, or kills unrelated user processes. **Restore baseline** re-applies the captured original power plan.