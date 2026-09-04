# ChatMPD

ChatMPD is a local-first autonomous Windows assistant built for Vader. One plain-language command is routed to the strongest appropriate local capability: general reasoning, verified coding, system inspection, ESO diagnostics, Vortex inventory, or local image/video generation.

The normal interface is `ChatMPD.exe`. The desktop and optional phone interface use the same orchestrator and the same local data. Model inference and media generation stay on Vader; no paid API is required for the default configuration.

> **Alpha software:** ChatMPD can modify project files and run local workloads. Coding changes are backed up and verified in an isolated snapshot, but backups and verification are not a substitute for normal source control or system backups.

## Current local stack

| Role | Default on Vader |
| --- | --- |
| Deep/general reasoning | gpt-oss-20B MXFP4 through llama.cpp |
| Coding specialist | Qwen2.5-Coder-7B-Instruct Q4_K_M |
| Fast worker/router candidates | Qwen2.5-Coder-1.5B variants |
| Retrieval/embeddings | Nomic Embed Text V2 |
| Image generation | Z-Image-Turbo NVFP4 through ComfyUI |
| Video generation | LTX-Video 2B distilled FP8 through ComfyUI |
| Media assembly | FFmpeg |

ChatMPD discovers compatible local GGUF models instead of hard-coding one model forever. The role manager keeps at most one llama.cpp model active at a time and swaps models when the task changes.

## One front door

Double-click `ChatMPD.exe`, type what you want, and select a project folder only when the request involves project code. Examples:

- `Explain why this Windows process is using so much memory.`
- `Scan my ESO add-ons and tell me the highest-risk compatibility problems.`
- `Show me what Vortex is managing.`
- `Fix the failing calculator test in this project.`
- `Create a photorealistic image of a desert sunrise.`
- `Create a ten-second cinematic video of a snowy forest.`

Routing, model selection, backend choice, and verification happen underneath the same interface.
## Verified coding path

Coding remains deliberately stricter than general host assistance. ChatMPD profiles the selected Python project, collects bounded local Git context, and permits only workspace-contained tools:

- bounded file inventory
- bounded UTF-8 reads
- bounded text search with secret/path exclusions
- atomic whole-file writes
- exact surgical text replacement
- one pre-approved verification command

Existing files are backed up under `.chatmpd/runs/<run-id>/backups/` before the first change in that run. Verification executes against a filtered copy in WSL Ubuntu plus bubblewrap with networking unshared. A coding run cannot report success until every required check passes after the most recent write.

The current verified project profile is Python: standard-library `unittest` discovery when recognized, otherwise `compileall`. The hardened coding engine is intentionally not weakened to provide broad shell access.

## ESO and Vortex

The ESO specialist reads manifests, `AddOnSettings.txt`, dependency state, Minion metadata and other local evidence. Modern `.addon` manifests are supported. Safe repair/install paths create backups and refuse mutation while ESO or Minion is active.

The Vortex specialist currently provides read-only inventory of Vortex version, managed game state, profiles, staging/mod folders and snapshots. It does not mutate Vortex's live LevelDB or deployment state.

## Local media

ComfyUI runs as a hidden loopback-only backend at `127.0.0.1:8188`. ChatMPD owns workflow selection so the user does not need to manage nodes manually. The media runtime uses DynamicVRAM and asynchronous weight offload for Vader's RTX 3060 12 GB and refuses to start GPU media generation while ESO is running.

Longer video requests are split into hardware-safe LTX segments and assembled with FFmpeg. Media requests remain subject to ChatMPD's supported-content boundaries; model/backend configuration is not used to bypass safeguards.
## Mobile access

The desktop window can start a private-network mobile gateway. The phone receives a lightweight browser interface while Vader performs all inference and tool work.

Pairing uses a short-lived one-time code. The returned device token is stored on the phone; ChatMPD persists only its SHA-256 digest and supports revocation. llama.cpp and ComfyUI stay bound to loopback and are never directly exposed by the mobile gateway.

The local gateway is intended for a trusted private network. Remote-away-from-home access should be placed behind a private network overlay such as Tailscale/WireGuard rather than exposing the gateway directly to the public internet. ChatMPD does not change Windows Firewall automatically.

## Resource behavior

When `eso64.exe` is detected, ChatMPD starts llama.cpp CPU-only at idle priority and does not start GPU media generation. When ESO is not running, llama.cpp uses automatic GPU offload. The role manager unloads language-model resources before specialist/media work to reduce VRAM contention.

Local models and media assets live outside the executable, primarily under `D:\ChatMPD`. Large model files are not packaged into Git or `ChatMPD.exe`.

## Optional command line

The desktop app is the primary interface. Source installations retain the deterministic diagnostic/coding commands:

```powershell
python -m chatmpd doctor
python -m chatmpd run --workspace "C:\Projects\example" --task "Fix the failing unit test"
python -m chatmpd demo
```

`doctor` checks the local coding runtime and sandbox without performing a task. `run` executes one verified project task. `demo` exercises the deterministic vertical slice without requiring a live LLM.
## Local records and trust boundaries

Conversation history is stored locally under `%LOCALAPPDATA%\ChatMPD\conversations`. Coding runs store compact records and eligible backups inside the selected project's `.chatmpd` directory. Raw file contents and verification stdout/stderr are not duplicated into persistent run-event logs.

ChatMPD does not claim perfect containment or guaranteed model correctness. Windows, WSL, llama.cpp, ComfyUI, FFmpeg, installed model files and the host account remain trusted dependencies. Critical system boundaries—boot/firmware, disks/partitions, security controls, credentials, accounts/permissions and similarly destructive operations—remain explicit escalation points.

## Documentation

- [Architecture](docs/architecture.md)
- [Most Effective Usage](docs/most-effective-usage.md)
- [Windows setup](docs/setup-windows.md)
- [Security model](docs/security.md)
- [Troubleshooting and recovery](docs/troubleshooting.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## License and independence

ChatMPD is licensed under the [MIT License](LICENSE). Third-party software and models retain their own licenses. The behavior doctrine is an original synthesis of local-first autonomy, evidence, bounded tools and verification; third-party agent/prompt material supplied during development is treated as design reference rather than copied product instructions.
