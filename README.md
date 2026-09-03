# ChatMPD

ChatMPD is a local-first Windows coding agent for supported Python projects. You choose a project folder, describe a change, and ChatMPD can inspect and edit project files before running a fixed verification check in a disposable, offline Linux snapshot.

The normal interface is a small Windows desktop window. The model runs on your computer through [llama.cpp](https://github.com/ggml-org/llama.cpp) with the official [Qwen2.5-Coder-7B-Instruct GGUF](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF). Those two large external components are installed separately and are not included in this repository or the ChatMPD executable.

> **Alpha software:** ChatMPD can modify real files. It creates backups of eligible existing files before replacing them, but it is not a substitute for your own backup or a clean Git working tree. Review every result.

## At a glance

| Question | Current behavior |
| --- | --- |
| Where does inference run? | On this Windows PC, using a local `llama-server.exe` and local GGUF model. |
| Does it need a paid API? | No. ChatMPD has no paid API, per-call fee, API key, or vendor quota. Hardware capacity, electricity, storage, context size, output size, and turn limits still apply. |
| What projects can it work on? | Python projects only in the current release. |
| What checks can it run? | Exactly Python `unittest` discovery or `compileall`, selected from the project profile. It cannot invent or run an arbitrary shell command. |
| Where do checks run? | In an offline copy of the project inside the WSL distro named `Ubuntu`, isolated further with bubblewrap. |
| Does it operate on GitHub? | No. It reads bounded local Git status/diff context when available; it does not fetch, push, create branches, open pull requests, or mutate a remote. |
| How is state kept? | Each task that reaches the agent engine gets a local `.chatmpd/runs/<run-id>/` record inside the selected project, including eligible pre-edit backups. A prerequisite failure before the engine starts may have only a GUI/CLI error and runtime log. |

## Quick start

If ChatMPD is already installed on this computer:

1. Double-click `ChatMPD.exe`. Double-clicking opens the graphical interface; a terminal is not required.
2. If Microsoft Defender SmartScreen says the app is unrecognized, verify where the file came from before choosing **More info** and **Run anyway**. Current local builds are unsigned, so this warning is expected. Do not bypass the warning for a file you do not trust.
3. Select **Choose project** and choose a Python project folder. A Git repository is recommended but not required.
4. Enter a specific task, such as “Fix the failing total calculation and keep the public function names unchanged.” Never put passwords, tokens, or other secrets in the task text.
5. Select **Start task** and leave the project files alone until the task finishes.
6. Review the summary, changed-file list, and check result. The window shows the exact path to the saved run record.

For first-time installation, model placement, WSL, and bubblewrap instructions, see [Windows setup](docs/setup-windows.md).

## What happens during a task

1. `prepare_project_task()` validates the request, inventories a bounded set of safe project files, collects sanitized local Git context when available, and selects the one supported Python verification command. This preflight completes before ChatMPD enters `LlamaCppRuntime`.
2. ChatMPD then requires the loopback endpoint at `127.0.0.1:8080` to be idle and starts its own llama.cpp server. It refuses any already-healthy service on that endpoint, including one advertising ChatMPD's alias.
3. Using the prepared project context, it asks the local Qwen model to plan the task. Verification uses `unittest` discovery when preflight recognizes a standard-library unittest case under `tests/`, otherwise Python bytecode compilation with `compileall`.
4. The agent can list, read, or atomically replace permitted UTF-8 project files. Protected state and known secret paths are denied.
5. Before an existing file is replaced, its original contents are copied to that run's `backups/` folder, subject to the 256 KiB file limit.
6. Verification receives a filtered snapshot rather than the live project. WSL Ubuntu and bubblewrap run the exact approved Python command with networking unshared and the environment cleared.
7. ChatMPD accepts success only after every required check has passed after the last write.
8. The llama.cpp server started and owned by this task is stopped when the task ends, including error paths. A pre-existing listener is refused and is never treated as an owned process to stop.

The detailed component and data flow is in [Architecture](docs/architecture.md). Security boundaries and residual risks are in [Security model](docs/security.md).

## Game-aware performance mode

ChatMPD checks for the exact Windows process name `eso64.exe` immediately before it starts its own model server.

When that game is detected, llama.cpp is started in a deliberately conservative mode:

- CPU-only inference (`0` GPU layers)
- one inference thread
- one batch-processing thread
- Windows `IDLE` process priority
- one parallel request

When `eso64.exe` is not detected, llama.cpp uses automatic GPU offload. If the ESO detection operation cannot complete, ChatMPD conservatively chooses CPU-safe mode. The WSL verification step can still consume CPU time, memory, and disk bandwidth in either mode, and creating the project snapshot also performs disk I/O. Game-aware mode reduces interference; it cannot guarantee a particular frame rate or eliminate all resource use. It currently recognizes only `eso64.exe`.

See [Troubleshooting: game performance](docs/troubleshooting.md#the-game-slows-down-while-chatmpd-is-working) for practical mitigations.

## Supported projects and safety limits

ChatMPD currently supports only projects containing Python files:

- If the safe project scan recognizes a standard-library `unittest.TestCase` or `unittest.IsolatedAsyncioTestCase` with a `test*` method in `tests/test*.py`, it selects `/usr/bin/python3 -m unittest discover -s tests`.
- Otherwise it selects `/usr/bin/python3 -m compileall -q .`.
- If no Python files are found, ChatMPD refuses the task because it has no approved offline verification gate.

Important built-in limits include:

- 32 KiB maximum task text
- 8,192-token llama.cpp context and at most 512 generated tokens per response by default
- at most 50 model turns and one tool call per turn
- 256 KiB per file for agent reads, writes, and backups
- 60 seconds and 64 KiB combined captured output per verification command
- 20,000 files, 256 MiB total, and 64 MiB per file in a verification snapshot

These are safety and predictability limits, not cloud-provider quotas. A small local model can still misunderstand a task, make an incomplete change, or fail to fit a large project into its bounded context.

## Records, backups, and recovery

Each task that reaches the agent engine creates:

```text
<project>/.chatmpd/runs/<run-id>/
├── run.json
├── events.jsonl
└── backups/
    └── <original project paths, when eligible>
```

`run.json` contains task status, summary, changed paths, and verification metadata. `events.jsonl` contains a compact event trail. Read-file contents and raw verification output are deliberately not written to these records; hashes and byte counts are stored instead. The task text and final summary are stored, so do not type secrets into the task.

Backups are not an automatic rollback system. They contain the original version of an existing file the first time ChatMPD replaces it during that run. Newly created files have no original to back up. For step-by-step restoration, see [Recovery](docs/troubleshooting.md#recovering-from-an-unwanted-change).

## Optional command line

The graphical interface is the default. Source installations also expose these optional PowerShell commands:

```powershell
python -m chatmpd doctor
python -m chatmpd run --workspace "C:\Projects\example" --task "Fix the failing unit test"
python -m chatmpd demo
```

- `doctor` checks discovery of llama.cpp and the model, reports game mode, and probes the WSL sandbox without starting model inference.
- `run` performs one live local-model task and prints its status, changed files, checks, and run-record path.
- `demo` creates a credential-free sample project and repairs it with a deterministic scripted model. It does not use the GGUF model, but its verification still requires the WSL sandbox.
- `python -m chatmpd` with no arguments opens the GUI.

Command-line details and exit codes are documented in [Troubleshooting](docs/troubleshooting.md#optional-command-line-diagnostics).

## Documentation

- [Most Effective Usage](docs/most-effective-usage.md)
- [Windows setup](docs/setup-windows.md)
- [Architecture](docs/architecture.md)
- [Security model](docs/security.md)
- [Troubleshooting and recovery](docs/troubleshooting.md)
- [Security reporting policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## What ChatMPD does not promise

ChatMPD does not provide a perfect sandbox, a proof of privacy, or a guarantee that model output is correct. The Windows process retains the current user's access to the selected project, the local loopback server is accessible to other local processes, WSL is a separate system dependency, and source files can contain secrets that no filename filter can recognize. Use a backed-up project, review changes, and keep the host, WSL distro, llama.cpp, and model files trustworthy.

## License and independence

ChatMPD is licensed under the [MIT License](LICENSE). Repository history includes an MIT-licensed Anthropic Claude Code Action snapshot preserved for attribution at the local tag `archive/claude-code-action-import`; see [Third-party notices](THIRD_PARTY_NOTICES.md). Anthropic does not maintain, sponsor, or support ChatMPD.
