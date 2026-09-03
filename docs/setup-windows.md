# Windows setup

This guide prepares a Windows 11 computer for ChatMPD. The current owner machine already has these prerequisites, but a fresh computer or rebuilt installation needs each layer below.

ChatMPD itself is small. The local model, llama.cpp server, and Linux isolation tools are separate installations and are not bundled with the source tree or `ChatMPD.exe`.

## What you need

- 64-bit Windows 11
- enough free disk space for the Qwen GGUF model, llama.cpp, WSL Ubuntu, project snapshots, and normal project files
- Windows Subsystem for Linux 2 with a registered distribution named exactly `Ubuntu`
- `bubblewrap`, Python 3, `tar`, and `timeout` available in that Ubuntu distribution
- [llama.cpp](https://github.com/ggml-org/llama.cpp)'s Windows `llama-server.exe`
- the official [Qwen2.5-Coder-7B-Instruct GGUF](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF), `Q4_K_M` quantization, stored below `D:\ChatMPD\models\huggingface`
- for running from source: CPython 3.11 or newer, including Tk support

There is no paid model API, API key, per-call fee, or vendor quota. The one-time component downloads need internet access, and local use consumes the computer's storage, memory, CPU/GPU time, power, and cooling capacity.

## 1. Install WSL 2 and Ubuntu

Follow Microsoft's current [Install WSL](https://learn.microsoft.com/windows/wsl/install) guidance. In an Administrator PowerShell window, the normal command is:

```powershell
wsl --install -d Ubuntu
```

Restart Windows if prompted. Launch **Ubuntu** once from the Start menu and complete its first-run username/password setup.

ChatMPD currently asks WSL for a distribution whose registered name is exactly `Ubuntu`. Names such as `Ubuntu-22.04` or `Ubuntu-24.04` are not treated as aliases. Check the registered name in PowerShell:

```powershell
wsl --list --verbose
```

The `Ubuntu` row should show WSL version `2`. If it does not, follow Microsoft's WSL documentation before continuing. Changing or removing a WSL distribution can destroy its Linux-side data; do not unregister an existing distribution merely to change its display name.

## 2. Install the Ubuntu sandbox packages

Open the **Ubuntu** app. At its Linux prompt, run:

```bash
sudo apt update
sudo apt install --yes bubblewrap python3 tar coreutils
```

`coreutils` supplies the `timeout` command used by ChatMPD. Confirm the key executables:

```bash
/usr/bin/bwrap --version
/usr/bin/python3 --version
/usr/bin/tar --version
/usr/bin/timeout --version
```

Close Ubuntu when installation is complete. ChatMPD invokes it in the background only for a sandbox health probe and approved Python verification commands.

## 3. Install llama.cpp for Windows

The simplest supported layout uses the Windows Package Manager. In PowerShell:

```powershell
winget install --exact --id ggml.llamacpp
```

ChatMPD looks for `llama-server.exe` in either location:

1. an absolute directory on the Windows `PATH`
2. the current user's WinGet package area below `%LOCALAPPDATA%\Microsoft\WinGet\Packages\ggml.llamacpp_*`

If installing manually from an official llama.cpp release, put the complete matching Windows runtime files together and add that directory to the user `PATH`. Do not rename an unrelated executable to `llama-server.exe`. Use a source and build you trust.

Open a new PowerShell window after installation and check discovery:

```powershell
Get-Command llama-server.exe
```

It is acceptable for that command to be absent when WinGet installed the package but did not expose a command alias; ChatMPD also searches the WinGet package directory directly. The later `doctor` check is authoritative for ChatMPD discovery.

## 4. Download the Qwen GGUF model

Open the official [Qwen2.5-Coder-7B-Instruct-GGUF file list](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/tree/main) and locate filenames containing both:

```text
qwen2.5-coder-7b-instruct
q4_k_m
```

Create ChatMPD's current model root in PowerShell:

```powershell
New-Item -ItemType Directory -Force "D:\ChatMPD\models\huggingface"
```

Download the `Q4_K_M` GGUF file into that root or any subdirectory below it. The official quantization can be split into numbered parts. If a selected filename ends with a pattern such as `-00001-of-00002.gguf`, download every part through the stated total into the same folder. ChatMPD rejects an incomplete split.

Keep the original descriptive filenames. ChatMPD recursively searches for `.gguf` files whose names identify `Qwen2.5-Coder-7B-Instruct` and `Q4_K_M`; it selects the first complete match in sorted order.

The current GUI does not expose a model-location setting. Its default root is specifically:

```text
D:\ChatMPD\models\huggingface
```

If the computer has no `D:` volume, either provision a suitable `D:` location or have a developer supply a reviewed build with an explicit `RuntimeConfig.model_path`/`cache_root`. Do not download a different model and rename it to look compatible.

Review the model repository's model card and license before downloading, using, or redistributing weights. Model weights and their license remain separate from ChatMPD's MIT License.

## 5. Install or run ChatMPD

### Packaged Windows app

Place `ChatMPD.exe` in a normal user-owned application folder and double-click it. The executable is windowed and should open the ChatMPD GUI without a console window.

Current locally produced executables are unsigned. Microsoft Defender SmartScreen may display **Windows protected your PC** because the publisher is unknown. If—and only if—you obtained or built the exact file from a source you trust, choose **More info**, inspect the application name, then choose **Run anyway**. A SmartScreen warning is not proof that a file is safe; do not bypass it for an unexpected copy.

The packaged executable does not include llama.cpp or the Qwen model. WSL Ubuntu and bubblewrap also remain system prerequisites.

### Run from source

Open PowerShell in the ChatMPD repository and create a virtual environment:

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

Confirm the displayed interpreter is a 64-bit CPython 3.11 or newer. If the `py` launcher is unavailable, substitute the full path to a supported Python installation. Start the GUI with:

```powershell
.\.venv\Scripts\python.exe -m chatmpd
```

Running this source command from a terminal naturally leaves that terminal visible. Use the packaged windowed executable when you do not want a console window over another application.

### Build the windowed executable from source

Building is optional and intended for a trusted local source tree:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
.\.venv\Scripts\pyinstaller.exe --clean ChatMPD.spec
```

The result is normally `dist\ChatMPD.exe`. PyInstaller packaging does not sign it. Distributors are responsible for applicable third-party notices and code signing; see [Third-party notices](../THIRD_PARTY_NOTICES.md).

## 6. Check readiness

From a source/virtual-environment PowerShell prompt, run:

```powershell
.\.venv\Scripts\python.exe -m chatmpd doctor
```

`doctor` does not start model inference. It checks:

- whether ChatMPD can discover `llama-server.exe`
- whether it can discover a complete Qwen `Q4_K_M` GGUF
- whether the default endpoint is stopped or is already occupied (an existing ChatMPD-alias service is also a conflict for a new task)
- whether `eso64.exe` is running and which performance mode would be selected
- whether WSL `Ubuntu` plus bubblewrap can create the required isolation boundary

An idle/stopped endpoint is normal: ChatMPD starts its owned server only when a live task needs it. An already-healthy endpoint must be closed before a new task, even if it advertises `chatmpd-local`, because ChatMPD does not borrow another process. `Overall: ready` means the prerequisites were found, the endpoint was idle, and the sandbox probe succeeded.

If using only the packaged GUI, you may skip the source environment and proceed to a small task. Setup failures appear in the GUI result; [Troubleshooting](troubleshooting.md) maps those messages to recovery steps.

## 7. Run a cautious first task

1. Use a small Python project that is backed up and does not contain real credentials.
2. If it has standard-library unit tests, keep direct `unittest.TestCase`/`unittest.IsolatedAsyncioTestCase` classes with `test*` methods in root-level `tests/test*.py` files so the current static profiler can recognize them.
3. Double-click `ChatMPD.exe` or start the source GUI.
4. Choose the project folder.
5. Request one small, reviewable change.
6. Wait for **Task finished successfully** or the failure summary.
7. Review the changed files and local diff before using the result.

ChatMPD creates `.chatmpd/runs/<run-id>/` inside that project. Consider adding `.chatmpd/` to the project's own ignore rules so recovery records are not committed or synced, while retaining the records locally until the change is accepted.

## Installed locations used by default

| Item | Default/discovery location |
| --- | --- |
| ChatMPD project state | `<selected-project>\.chatmpd\runs\<run-id>\` |
| llama.cpp runtime log | `%LOCALAPPDATA%\ChatMPD\runtime\llama-server.log` |
| llama.cpp server | Windows `PATH` or `%LOCALAPPDATA%\Microsoft\WinGet\Packages\ggml.llamacpp_*\...\llama-server.exe` |
| Qwen model search root | `D:\ChatMPD\models\huggingface\` |
| model endpoint | `http://127.0.0.1:8080` |
| WSL distribution | registered name `Ubuntu` |
| temporary verification copy | `/tmp/chatmpd-sandbox-<random-id>/work` inside Ubuntu; removed on normal exit |

For why these pieces are separate, see [Architecture](architecture.md). For trust and privacy implications, see [Security](security.md).
