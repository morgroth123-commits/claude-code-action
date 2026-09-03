# ChatMPD security model

ChatMPD combines a local language model, direct project-file edits, and isolated Python verification. The design reduces the authority given to model output, but it does not make model-generated changes inherently safe and does not claim perfect sandboxing or privacy.

For private vulnerability reporting, see the root [security policy](../SECURITY.md).

## Plain-language summary

- ChatMPD sends model requests only to a validated loopback llama.cpp URL. There is no cloud-model fallback, paid API, API key, per-call fee, or vendor quota in the current code.
- The agent is not given a terminal. It receives four tools: bounded listing, bounded UTF-8 reading, atomic UTF-8 writing, and one exact approved Python verification command.
- Project execution happens on a filtered copy inside the WSL distro named `Ubuntu`, with bubblewrap networking unshared and capabilities dropped. The live Windows project is not mounted into that command environment.
- `.git`, `.chatmpd`, common secret directories, known credential filenames, environment files, and private-key/certificate formats are denied or omitted at relevant boundaries.
- ChatMPD can still read and change ordinary source files with the current Windows user's authority. A secret embedded in a normal-looking source file cannot be reliably identified by a path filter.
- Run records are local and avoid raw read contents and command output, but they do store task text, summaries, file paths, and error/verification metadata. Do not put secrets into task text.
- Local Git context is read-only. ChatMPD does not fetch, push, commit, create branches, open pull requests, or mutate a remote.

## Assets and trust boundaries

| Asset | Main control | Residual risk |
| --- | --- | --- |
| Selected project files | Workspace-relative canonical path checks, protected components, atomic writes, 256 KiB limit, pre-edit backup. | The Windows process has the owner's normal access; permitted files can be changed incorrectly. |
| Credentials and repository state | Sensitive names/extensions and secret directories are blocked; `.git` and `.chatmpd` are protected; scans and snapshots filter them. | Secrets in ordinary source, unusual filenames, generated output, task text, or error text may not be recognized. |
| Verification execution | Exact argv allowlist, no project shell, filtered copy, WSL Ubuntu, bubblewrap namespaces, no network namespace, cleared environment, dropped capabilities, time/output limits. | WSL/kernel/distro/bubblewrap bugs or host compromise remain possible; resource exhaustion is bounded but not eliminated. |
| Local model traffic | Plain HTTP restricted to loopback syntax, proxy bypass, endpoint diagnostics/identity alias, exclusive per-task endpoint ownership, request/response shape and size checks. | Loopback has no TLS or authentication; another local process can observe, impersonate, or call a local server subject to OS controls. |
| Model and server files | Explicit local discovery and separate installation. | A tampered binary or model has not been made trustworthy merely by being local. |
| Local Git context | Resolved Git executable, noninteractive read-only subcommands, bounded output, credential-free origin parsing, sensitive diff filtering. | Git itself and repository configuration remain local trust dependencies; sanitizers cannot understand every data format. |
| Recovery records | Per-run directory protected from model tools and excluded from snapshots; raw reads/command output replaced by metadata and hashes. | Task text, summary, paths, tool-error messages, and timing/status metadata persist until the owner deletes them. |
| Game performance | ESO detection selects CPU-only, one-thread, idle-priority inference and unloads an owned server after the task. | WSL, snapshot I/O, memory use, and CPU inference can still affect the game. |

## Project discovery and protected paths

Before model use, ChatMPD scans a bounded inventory. It skips symbolic links and junctions so they cannot redirect discovery outside the selected folder. The project manifest and WSL snapshot exclude internal state, environments, common caches/build outputs, and these common secret locations:

```text
.aws  .azure  .ssh  .secrets  secret  secrets
```

Direct agent path access also protects those directory components plus:

```text
.git  .chatmpd
```

Known sensitive files include `.env` and `.env.*` (except `.env.example`), `.netrc`, `.npmrc`, `.pypirc`, common identity-key and service-account filenames, and `.key`, `.pem`, `.p12`, and `.pfx` files. Windows reserved device names, trailing-dot/space aliases, invalid characters, absolute paths, parent traversal, links, junctions, and paths resolving outside the workspace are rejected.

These rules protect common high-risk cases; they are not content inspection. For example, `src/settings.py` or `notes.txt` could contain a token and still look like an ordinary source file. Keep secrets out of the selected project when practical, use environment/credential stores, and review what a task requires before starting it.

## Local model and loopback endpoint

The runtime accepts only a plain-HTTP URL whose hostname is `127.0.0.1`, `localhost`, or `::1`, with a port and no credentials, query, or fragment. The default is `http://127.0.0.1:8080`. The provider explicitly disables proxy handling.

ChatMPD probes `/health` and `/v1/models` for endpoint diagnostics and the alias `chatmpd-local`. A new runtime refuses every already-healthy endpoint, including a service with that alias, rather than borrowing or terminating a process it does not own. If ChatMPD starts llama.cpp, it supplies the local model path, binds to `127.0.0.1`, disables the web UI, limits parallelism, and keeps a handle so it can terminate that owned process at task exit.

Loopback is a routing restriction, not an authentication or encryption mechanism. Other processes running as the user may be able to connect to the port. Host malware or a malicious local service remains outside ChatMPD's protection. Use trusted llama.cpp binaries and model files, keep Windows patched, and do not expose or forward port `8080`.

Game detection also follows a fail-safe preference: if the `eso64.exe` detector cannot complete, ChatMPD chooses the lower-impact CPU-safe llama.cpp settings rather than assuming GPU-auto mode is safe.

ChatMPD itself does not include cloud inference or telemetry in the task path. That is narrower than a promise that no component on the computer ever uses a network: Windows, WSL, Ubuntu, package managers, security software, Git helpers, or a separately installed binary may have their own behavior. Verification specifically unshares its network namespace, but host components remain independently administered.

## Model authority and command policy

The local model proposes actions; it does not receive direct Python, PowerShell, Command Prompt, Bash, WSL, Git, or network tools. Tool schemas allow:

- `list_files`
- `read_file`
- `write_file`
- `run_command`

The service populates the command policy with one exact Python argv chosen before the model loop. `PermissionPolicy` compares the full argument sequence, so an added flag, changed path, shell metacharacter, or different executable is denied. `subprocess`/WSL launch APIs receive argument lists with shell execution disabled around the approved project command.

Exact allowlisting does not make the code under test harmless. Python `unittest` discovery imports and executes project-supplied test modules, and those tests can import application code. That untrusted project execution receives access to the filtered `/work` copy and can consume resources, but it is kept away from the live Windows project and host network by the sandbox design. `compileall` compiles source without intentionally running module top-level code, but it still processes untrusted files through the Python toolchain.

Success is gated independently of the model's wording: each required command must have passed after the most recent write. The engine allows at most 50 turns, while the model adapter requests a single tool call per turn. These rules reduce prompt-injection authority but do not ensure that the allowed edit itself is correct or that the selected check has adequate test coverage.

## WSL Ubuntu and bubblewrap verification

ChatMPD creates an in-memory temporary tar snapshot of safe regular files. The live workspace, `.git`, `.chatmpd`, secrets, caches, virtual environments, and links are not mounted into bubblewrap. The snapshot is extracted under a random `/tmp/chatmpd-sandbox-*` directory inside WSL and deleted by the guest cleanup handler.

The bubblewrap invocation uses:

- new user, PID, network, IPC, and UTS namespaces
- `--cap-drop ALL`
- read-only `/usr`, `/lib`, and `/lib64`
- a minimal `/proc` and `/dev`
- empty `/etc`, `/home`, and `/run`
- temporary `/tmp`
- only the extracted project copy writable at `/work`
- a cleared environment with fixed `HOME`, locale, `PATH`, Python cache, and temporary-directory values
- a new session, parent-death behavior, and an inner timeout

Windows applies a second timeout and attempts process-tree termination and guest-root cleanup if needed. Snapshot file count/size, command duration, command-argument length, and captured output are bounded.

This is meaningful defense in depth, not a formal security proof. The WSL virtual machine/kernel integration, Ubuntu userland, bubblewrap, tar handling, Python interpreter, Windows host, and hardware remain in the trusted computing base. A denial-of-service, kernel escape, implementation flaw, side channel, or resource spike may still be possible.

## Git behavior

Git context is optional. When Git is available, ChatMPD resolves an executable from an absolute `PATH` entry and runs local read-only commands to identify the root/branch/origin name and collect status/diff. If the owner selected a subdirectory of a larger repository, status and diff receive a top-anchored literal pathspec for only that selected subtree; a repository-root selection includes the whole repository. Credential prompts and optional locks are disabled; diff helpers and text conversion are disabled; Windows launches request no visible console. Origin parsing keeps only safe owner/repository components, not credentials or the full remote URL.

ChatMPD has no product tool for `fetch`, `pull`, `push`, `commit`, `checkout`, `switch`, branch deletion/creation, tag mutation, issue mutation, or pull-request creation. The WSL command allowlist also excludes Git. A human may use Git separately for backup and review.

## Records, backups, and privacy

Every engine attempt creates `.chatmpd/runs/<run-id>/` before the model loop:

- `run.json` stores the task, final status/summary, changed-file paths, required-check argv/exit code/sequence, byte counts, hashes, and event count.
- `events.jsonl` stores timestamps, event types, plan steps, permission decisions, tool names, file paths/byte counts/hashes, write metadata, and tool-failure messages.
- `backups/` stores an original existing file before its first replacement in that run, up to 256 KiB.

The persisted version of a successful `read_file` event omits content. Persisted command events omit stdout/stderr and store size/hash metadata. Model chat messages are not written as a transcript. However:

- task text and final summary are stored verbatim
- an error message can contain a path or bounded diagnostic detail
- filenames themselves may be sensitive
- a backup contains the complete original file by design
- the llama.cpp server log persists separately at `%LOCALAPPDATA%\ChatMPD\runtime\llama-server.log`

Treat the project and its `.chatmpd` folder as private local data. Limit filesystem access using normal Windows accounts, do not sync or commit `.chatmpd`, inspect logs before sharing them, and delete records only after you no longer need recovery/audit information.

## Owner checklist

Before a task:

1. Use a trusted copy of ChatMPD, llama.cpp, bubblewrap/Ubuntu packages, and the Qwen model.
2. Keep Windows and WSL maintained.
3. Use a backed-up project or review a clean local Git baseline.
4. Remove credentials from ordinary project files where possible.
5. Do not include credentials, private customer data, or unrelated personal information in task text.
6. Close any unrelated service using port `8080` rather than asking ChatMPD to take it over.

After a task:

1. Review the changed-file list and actual diff.
2. Confirm the selected verification command was appropriate for the project.
3. Treat a passing `compileall` check as syntax validation only, not behavioral correctness.
4. Restore an original from the run backup or local Git if the edit is unwanted.
5. Keep or remove run records according to your recovery and privacy needs.

See [Troubleshooting and recovery](troubleshooting.md) for concrete steps.
