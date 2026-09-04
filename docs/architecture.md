# ChatMPD 0.2 architecture

ChatMPD is a local-first autonomous assistant whose public interface is a plain-language command. The architecture separates general orchestration from hardened specialist capabilities so adding host/media/game features does not weaken the verified coding boundary.

## High-level flow

```text
Desktop GUI ─┐
             ├─> ChatMPDOrchestrator -> RequestRouter -> capability
Mobile PWA ──┘          |
                         +-> reasoning chat -> ModelRuntimeManager -> llama.cpp
                         +-> coding -> hardened AgentEngine -> WSL/bubblewrap checks
                         +-> system -> bounded host inspection
                         +-> ESO -> evidence scan / guarded reversible management
                         +-> Vortex -> read-only inventory
                         +-> media -> MediaRuntime -> ComfyUI -> output/FFmpeg
```

Desktop and mobile call the same orchestrator. The orchestrator serializes commands so two clients cannot race model swaps or GPU work.

## Model layer

`ModelRegistry` discovers compatible local GGUF files below configured model roots and assigns roles. Complete numbered split GGUFs are represented once using shard 1; incomplete splits are ignored.

Vader's current roles are:

- reasoning: gpt-oss-20B MXFP4
- coding: Qwen2.5-Coder-7B-Instruct Q4_K_M
- fast: Qwen2.5-Coder-1.5B variants
- embedding: Nomic Embed Text V2

`ModelRuntimeManager` keeps at most one llama.cpp role active at a time. General chat activates reasoning; project tasks activate coding. Specialist work releases the active LLM first. llama.cpp stays on loopback and is never exposed directly to mobile clients.

## Shared behavior doctrine

`chatmpd.doctrine` supplies original product rules shared by chat and coding prompts: local-first operation, evidence before claims, preservation of existing work, autonomy for ordinary reversible actions, and explicit escalation at critical system boundaries.
## Hardened coding capability

The coding engine remains project-only. `prepare_project_task()` resolves a supported Python project, builds a bounded safe manifest, sanitizes local Git context, selects one exact verification command, and proves the WSL/bubblewrap sandbox is available before model execution.

The coding model can use only:

- `list_files`: bounded safe inventory
- `read_file`: bounded UTF-8 read
- `search_text`: bounded safe text search
- `write_file`: atomic bounded replacement/create
- `replace_text`: exact-count surgical replacement
- `run_command`: one exact pre-approved argv

Paths are workspace-relative and reject traversal, symlinks/junctions, Windows device aliases, `.git`, `.chatmpd`, common secret directories, environment files, credentials and private-key formats. Existing files are backed up before their first mutation in a run.

Verification runs on a filtered disposable snapshot, not the live project. The WSL/bubblewrap runner unshares networking, clears the environment, drops capabilities, applies file/time/output limits and executes the exact argv without a project-controlled shell. A success response is rejected unless required checks passed after the last write.

## General host capability

General host inspection is deliberately separate from the project sandbox. `SystemInspector` exposes bounded OS, CPU, memory, disk and GPU evidence. Broad host mutations must pass the central risk doctrine; critical system/security/account/storage operations are not silently escalated.

## ESO specialist

`EsoAddonManager` reads the ESO live directory, modern `.txt`/`.addon` manifests, `AddOnSettings.txt`, dependencies, Minion metadata and update evidence. Safe mutation paths create backups and refuse to run while ESO or Minion owns the relevant files. The specialist is designed to preserve required functionality and diagnose conflicts rather than blindly disable large addon sets.

## Vortex specialist

`VortexInventory` reads version/game/profile/mod/snapshot metadata without parsing or modifying Vortex's live LevelDB. Mutation support is intentionally deferred until deployment/rollback semantics can be verified independently.
## Media capability

`MediaPipeline` normalizes one request into a backend-neutral plan. `MediaRuntime` manages a hidden ComfyUI process bound to `127.0.0.1:8188`, using shared storage below `D:\ChatMPD\media\ComfyUI-Shared`. It attaches safely to an already-running local ComfyUI server but stops only a process it owns.

On Vader the runtime enables DynamicVRAM and two asynchronous offload streams. It refuses GPU media startup while `eso64.exe` is running.

Image generation uses a native Z-Image-Turbo workflow with an NVFP4 diffusion model, mixed-FP8 Qwen encoder and AE VAE. Video generation uses LTX-Video 2B distilled FP8 with an FP8 T5 encoder. Longer requests are decomposed into native temporal segments and identical-format segments are concatenated with FFmpeg.

The generic media adapter owns workflow mechanics, output discovery, segment planning and assembly. Supported-content boundaries remain part of the media doctrine and are not delegated to model permissiveness.

## Mobile gateway

`MobileGateway` is a thin-client gateway; it does not run models on the phone. It serves a lightweight browser interface and authenticated JSON API. Pairing is one-time and short-lived. Device tokens are random; only SHA-256 token digests persist on Vader, and device records are revocable.

The gateway accepts only loopback/private/link-local client addresses. llama.cpp and ComfyUI remain loopback-only behind it. ChatMPD never opens Windows Firewall automatically. The LAN gateway should be used only on a trusted private network; away-from-home access should use a private overlay rather than a public port forward.

## Resource coordination

When ESO is running, llama.cpp uses the existing CPU-safe/idle-priority mode and media GPU startup is denied. When ESO is not running, llama.cpp may use GPU offload. Model role switches stop the previous model first, and specialist routing releases the active language model before ComfyUI work.

## Persistence

Conversation history is stored under `%LOCALAPPDATA%\ChatMPD\conversations`. Mobile device digests are stored under `%LOCALAPPDATA%\ChatMPD\mobile`. Media runtime logs are under `%LOCALAPPDATA%\ChatMPD\media-runtime`. Coding audit/backups remain per-project under `.chatmpd/runs/<run-id>`.
## Release boundaries

The PyInstaller executable contains ChatMPD code and UI assets, including the canonical `MDRight-01.jpeg` derived Windows/PWA icons. Large GGUF, image and video model weights remain external on Vader and are discovered at runtime.

The application is not a perfect sandbox or virtualization boundary. Windows, WSL, bubblewrap, llama.cpp, ComfyUI, FFmpeg and installed model files remain trusted dependencies. Evidence-based verification reduces risk but does not prove model output correct.

## Extension strategy

New models should be added through role/capability metadata rather than new UI modes. New specialists should implement a narrow handler behind the orchestrator and retain their own evidence, mutation and rollback rules. This keeps ChatMPD's user experience stable while its local capabilities evolve.
