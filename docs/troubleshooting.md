# Troubleshooting and recovery

Start with the symptom you see. ChatMPD is designed to fail closed when a required local component, protected path, or verification boundary is unavailable.

## Quick diagnostic

If you have a source installation, open PowerShell in the repository and run:

```powershell
.\.venv\Scripts\python.exe -m chatmpd doctor
```

If ChatMPD is installed in another Python environment, use that environment's Python. `doctor` checks discovery and performs a lightweight WSL/bubblewrap probe; it does not start model inference or load the GGUF onto the CPU/GPU.

Expected healthy output reports:

- llama.cpp server: ready
- local model: ready
- model endpoint: stopped (will start when needed)
- performance mode: `cpu-safe` when `eso64.exe` is detected, otherwise `gpu-auto`
- sandbox: ready
- overall: ready

An endpoint reported as **stopped** is healthy idle state, not a missing service.

## Windows says “protected your PC”

Current local `ChatMPD.exe` builds are unsigned, so Microsoft Defender SmartScreen may not recognize the publisher.

1. Confirm the file came from the source or person you expected.
2. If a checksum or build record was supplied, verify it.
3. Right-click the file, inspect **Properties**, and confirm its location/name.
4. Only for a trusted file, choose **More info** and **Run anyway**.

Do not disable SmartScreen globally and do not bypass the warning for a file received unexpectedly. Signing and reputation are distribution concerns; the warning cannot be safely “fixed” from inside ChatMPD.

## The window does not open

For a packaged app:

1. Check Task Manager for an existing `ChatMPD.exe` window/process.
2. Start one copy from a normal user-owned folder rather than from inside an archive.
3. Confirm Windows security software did not quarantine the executable.
4. Rebuild or obtain a fresh trusted copy if the executable is incomplete.

For source:

```powershell
.\.venv\Scripts\python.exe -m chatmpd
```

Any import/startup error will remain visible in that PowerShell window. Confirm the interpreter is Python 3.11 or newer and that its Tk installation is available. Recreate the virtual environment if it points to a removed Python installation.

## A terminal window pops up over the game

The packaged `ChatMPD.exe` is configured as a windowed application, and ChatMPD's llama.cpp, process-detection, Git, WSL probe, sandbox, and cleanup launches request Windows' no-console mode. A persistent visible WSL/debug terminal is not intended behavior.

To minimize interruptions:

1. Use the current packaged `ChatMPD.exe`, not `python -m chatmpd`, `chatmpd doctor`, or another terminal-launched developer command while playing. A source command keeps its own terminal by design.
2. Close separately opened PowerShell, Windows Terminal, Ubuntu, WSL debug, and development sessions before starting the game, after saving anything in them.
3. Start only one ChatMPD task. The GUI prevents two tasks in its own window, but another ChatMPD copy or external WSL task is separate.
4. If a window appears, note its title and whether it coincides with task start, verification, or task finish. Do not blindly terminate it during a check.
5. After the task, use `doctor` outside the game and report a reproducible pop-up with the ChatMPD version, Windows version, window title, and timing.

Do not disable or unregister WSL as a workaround: ChatMPD requires WSL Ubuntu for verification, and unregistering a distro can erase its Linux-side data.

## llama.cpp server: missing

Install llama.cpp using the official project or WinGet:

```powershell
winget install --exact --id ggml.llamacpp
```

Open a new PowerShell session and retry `doctor`. ChatMPD searches `PATH` and the current user's WinGet package directory. If you installed a manual release, keep its matching runtime files together and add that directory to the user `PATH`.

Do not substitute `llama-cli.exe`; ChatMPD specifically needs `llama-server.exe` and its OpenAI-compatible endpoints.

## Local model: missing

ChatMPD currently searches recursively below:

```text
D:\ChatMPD\models\huggingface
```

The filename must identify both `Qwen2.5-Coder-7B-Instruct` and `Q4_K_M`. For a split GGUF, every numbered part must be present in the same directory. Recheck:

- spelling and quantization in the filename
- that the download completed rather than leaving a browser partial file
- that all split parts are present
- that the file is actually below the `D:` search root
- that security software has not quarantined it

Use the official [Qwen GGUF repository](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF). The GUI has no current model-path setting; see [Windows setup](setup-windows.md#4-download-the-qwen-gguf-model) if the computer has no `D:` volume.

## Model endpoint is occupied by another server

ChatMPD uses `http://127.0.0.1:8080` exclusively for the server it starts for one task. It refuses every already-healthy service, including one whose `/v1/models` response advertises `chatmpd-local`. This prevents one ChatMPD instance from borrowing or stopping another instance's server.

To identify the Windows listener in PowerShell:

```powershell
Get-NetTCPConnection -LocalPort 8080 -State Listen |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

Then inspect a returned process ID without stopping it:

```powershell
Get-Process -Id <process-id>
```

Close the owning application normally if you recognize it and it is safe to do so. Do not kill an unknown system/process solely to free the port. The current GUI does not expose a different endpoint setting; a developer can provide a reviewed configuration/build if port `8080` must remain occupied.

## llama.cpp exits, times out, or the model is not ready

Inspect the local runtime log:

```text
%LOCALAPPDATA%\ChatMPD\runtime\llama-server.log
```

The file is appended across starts. Look near the end for model-open errors, missing split parts, unsupported llama.cpp arguments, memory allocation failures, or backend initialization problems. Before sharing the log, remove personal paths and any sensitive diagnostic data.

Common recovery steps:

- confirm the server and GGUF came from trusted, compatible releases
- confirm all model split files exist and have finished downloading
- close another high-memory application and retry outside the game
- update/reinstall llama.cpp from its official source if its command-line options are too old
- check free storage and Windows memory/virtual-memory pressure

ChatMPD waits up to 90 seconds for its managed server. Slower hardware or antivirus scanning can exceed that limit. Repeated timeouts need a configuration/code review rather than repeated forced process termination.

If `llama-server.exe` remains after a task, verify its path and start time in Task Manager. ChatMPD stops only the process it started. A separately launched server is never borrowed or stopped, while an abrupt host/app crash can also prevent normal cleanup. End a process manually only after confirming it is the local server you intend to stop.

## Sandbox unavailable

The current sandbox requires all of the following:

- `wsl.exe`
- a WSL distribution registered exactly as `Ubuntu`
- WSL version 2
- `/usr/bin/bwrap`
- `/usr/bin/python3`
- `/usr/bin/tar`
- `/usr/bin/timeout`
- working Linux user/PID/network namespace support

Check the registered distro from PowerShell:

```powershell
wsl --list --verbose
```

Then open Ubuntu and install/repair the packages:

```bash
sudo apt update
sudo apt install --yes bubblewrap python3 tar coreutils
```

Retry `doctor`. If the probe reports a bubblewrap/user-namespace failure, update WSL and Ubuntu using official guidance and check whether an organization security policy disables the needed namespaces. Do not weaken the bubblewrap flags to make the probe pass: verification must stop when the intended boundary is unavailable.

If WSL itself is stuck, save work in every WSL distribution before using any WSL restart/shutdown operation, because those operations stop all Linux sessions.

## Unsupported project: no safe offline verification command

ChatMPD currently supports Python only. The safe scan must find at least one `.py` file.

- A root-level `tests/test*.py` file containing a statically recognizable direct `unittest.TestCase` or `unittest.IsolatedAsyncioTestCase` subclass with a `test*` method selects `python3 -m unittest discover -s tests`.
- Another Python project selects `python3 -m compileall -q .`.
- A project with no Python files is refused.

Choose the actual Python project root, not a parent folder containing only shortcuts, ignored caches, or a nested repository. Symbolic links and junctions are intentionally skipped. Pytest-style functions, indirect test base classes, tests outside the root-level lowercase `tests` directory, and test files that cannot be parsed as UTF-8 fall back to `compileall` in the current profiler. JavaScript, TypeScript, Rust, C#, Java, and other project execution are not supported by the current policy.

## The checks do not pass

A failed check is a real completion blocker. ChatMPD will not accept “success” merely because the model says it is done.

Remember the distinction:

- `unittest discover -s tests` runs behavioral tests discoverable by Python's standard library.
- `compileall -q .` checks Python syntax/compilation only. A pass does not demonstrate correct behavior.

Run the corresponding test suite yourself in the project's normal trusted development environment to see its full diagnostic output. ChatMPD intentionally does not persist raw sandbox stdout/stderr in `run.json` or `events.jsonl`; only byte counts and hashes are saved. Fix project setup or tests outside ChatMPD if they depend on packages/data that are not present in the filtered offline snapshot.

ChatMPD does not install dependencies, access package registries, activate a project virtual environment, or run `pytest`. A project requiring those behaviors is outside the current execution support even if it contains Python files.

## The task stops because of a protected path

ChatMPD denies `.git`, `.chatmpd`, common secret directories, environment files, known credential filenames, private-key/certificate files, path traversal, links/junctions, and Windows path aliases. This is intentional.

Do not rename a secret simply to bypass the policy. Make the needed change manually or redesign the task so credentials and repository internals remain outside model authority. If an ordinary non-sensitive file is falsely rejected, report the smallest synthetic path that reproduces the issue without including real data.

## The project snapshot is rejected

Default snapshot bounds are 20,000 regular files, 256 MiB total content, and 64 MiB for one file. Links/junctions and excluded caches/build environments are skipped.

Choose the narrowest real project root and move unrelated large assets outside it using your normal project workflow. Do not remove a required source/data file merely to make the limit pass. If the project genuinely needs more than the current bound, it is not supported safely by the default build.

## The model loops, runs out of context, or makes a poor change

The default server context is 8,192 tokens, each response is capped at 512 tokens, the engine allows 50 turns, and project/model observations are bounded. These are local safety limits rather than a vendor quota.

Try a smaller, more specific task in a narrower project folder. State the desired outcome, relevant file/function, and constraint without pasting large source files or secrets. A 7B local model can still misunderstand the project; do not repeatedly accept edits you have not reviewed.

If the run changed files before failing, use the recovery steps below.

## The game slows down while ChatMPD is working

ChatMPD detects only the exact process `eso64.exe`, at the point it starts its own llama.cpp server. When detected, the server uses CPU-only inference, one inference thread, one batch thread, zero GPU layers, one parallel request, and Windows `IDLE` priority.

That mode protects GPU headroom but cannot eliminate load:

- local CPU inference still uses a CPU thread and memory bandwidth
- building a verification snapshot reads project files
- WSL startup, extraction, Python tests, and cleanup use CPU, memory, and disk
- a pre-existing listener prevents a new ChatMPD task from starting and must be closed normally first
- games other than `eso64.exe` do not trigger this specific mode

Practical mitigations:

1. Start the game before starting the ChatMPD task so detection sees `eso64.exe`.
2. Close a separately launched/pre-existing `chatmpd-local` llama.cpp server normally; ChatMPD refuses to borrow it and can apply performance settings only to the server it starts.
3. Choose the narrowest project folder and ask for one small change.
4. Avoid tasks with long unit suites during latency-sensitive play.
5. Let the current check finish instead of repeatedly starting/canceling work, which repeats WSL and snapshot overhead.
6. If smooth play matters more than completion time, run ChatMPD between sessions.

A model server started and owned by the task is unloaded when the task finishes. WSL may retain its normal lightweight virtual-machine state according to Windows' WSL behavior; ChatMPD's temporary guest snapshot is removed on normal cleanup.

If the ESO process check itself cannot complete, ChatMPD conservatively selects CPU-safe mode instead of GPU-auto mode.

## Recovering from an unwanted change

ChatMPD keeps recovery material per run, but recovery is manual so it does not overwrite newer owner changes automatically.

1. Stop editing the affected project and let the current ChatMPD task finish or close it safely.
2. Copy the whole project to a separate safe location if additional recovery work could overwrite useful changes.
3. Use the result shown in the GUI/CLI to locate:

   ```text
   <project>\.chatmpd\runs\<run-id>\run.json
   ```

4. Open `run.json` in a text editor and review `changed_files`, status, summary, and checks.
5. Open the sibling `backups` folder. An existing file replaced during that run has its pre-task original at the same relative path below `backups`.
6. Compare the backup, current file, and any newer work. Copy the backup over the project file only when you are sure the entire original version is the desired recovery.
7. A file newly created by ChatMPD has no backup. Move it aside or delete it only after confirming it is listed for that run and contains no work you need.
8. If the project uses Git, inspect local status/diff and use your normal Git client to restore or selectively apply changes. ChatMPD does not commit, reset, or push for you.
9. Run the project's normal trusted checks after restoration.

Backups are created only for an existing file before its first ChatMPD replacement in that run and are capped at 256 KiB; the engine rejects an oversized existing file before writing it. Backups do not capture edits made by other programs during the task and are not a full project snapshot.

Do not delete the run folder until you have accepted the result or completed recovery. When it is no longer needed, close ChatMPD and remove that specific run folder through File Explorer (preferably using the Recycle Bin). Never delete the entire project just to remove ChatMPD state.

## Understanding run records and logs

Per-run records live at:

```text
<project>\.chatmpd\runs\<run-id>\
```

The model-server log lives at:

```text
%LOCALAPPDATA%\ChatMPD\runtime\llama-server.log
```

`run.json` and `events.jsonl` omit raw file-read contents and raw command output, but they are not anonymous. They can contain task text, summaries, local file paths, timestamps, plan steps, tool error messages, hashes, sizes, and check commands. `backups` contains full original file content. Review and redact before sharing any record.

ChatMPD protects `.chatmpd` from its own model tools and verification snapshot; ordinary Windows software and the user can still access it according to filesystem permissions.

## Optional command-line diagnostics

Source installations support:

```powershell
python -m chatmpd doctor
python -m chatmpd run --workspace "C:\Projects\example" --task "Fix the failing test"
python -m chatmpd demo
```

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Ready/success. |
| `1` | Attention needed, failed task/check, or task execution failure. |
| `2` | Invalid task/workspace or unsupported project. |
| `3` | Runtime/diagnostic prerequisite could not be used. |

`demo` uses a deterministic scripted model and no GGUF, credentials, or paid API, but it still invokes the WSL sandbox for its unit-test check. `doctor` probes the sandbox but does not load or start the model.

## When to report a problem

Report a reproducible ChatMPD defect after removing private data. For a security-boundary failure, use the private process in [SECURITY.md](../SECURITY.md). For a normal bug, include:

- version/commit and packaged-versus-source installation
- Windows version
- exact non-secret message
- `doctor` summary with personal paths removed
- whether `eso64.exe` was running
- whether the problem occurs in a tiny synthetic Python project

Never publish a real project, credential, model prompt transcript, `.chatmpd` backup, or unredacted server log merely to demonstrate a bug.
