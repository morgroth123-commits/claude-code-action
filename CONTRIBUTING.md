# Contributing to ChatMPD

Thank you for helping improve ChatMPD. The project is a small, standard-library-first Python application for Windows, with safety-sensitive local file access and isolated verification. Changes should stay understandable to a nontechnical owner and preserve the boundaries documented in [Architecture](docs/architecture.md) and [Security](docs/security.md).

## Before you begin

- Use Windows 11 and Python 3.11 or newer.
- Keep model weights, llama.cpp binaries, local run records, logs, build output, and credentials out of the repository.
- Most development and unit testing does not need a model, API key, WSL process, or network connection. Tests use injected fakes for external behavior.
- Live tasks and the offline demo do require the WSL Ubuntu/bubblewrap sandbox. A live task additionally requires llama.cpp and the Qwen GGUF model described in [Windows setup](docs/setup-windows.md).
- Work in a clean branch or otherwise preserve the owner's existing changes. Do not discard unrelated modifications.

## Development setup

From a PowerShell prompt in the repository root:

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

Confirm the displayed interpreter is CPython 3.11 or newer. If the `py` launcher is unavailable, use the full path to any supported CPython installation. Runtime code has no required third-party Python packages.

For the optional Windows executable build:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[build]"
.\.venv\Scripts\pyinstaller.exe --clean ChatMPD.spec
```

The build is intentionally windowed (`console=False`). Current local executables are unsigned and may trigger Microsoft Defender SmartScreen. Do not commit `build/`, `dist/`, an executable, or downloaded runtime/model files unless a release process explicitly calls for them.

## Run the checks

The primary repository checks are:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q chatmpd tests
```

Run the smallest focused test module while iterating, then the full unit suite before proposing a change. Ordinary automated tests must not start a real model, invoke a live WSL task, download software, access a project outside their temporary directory, or depend on a paid service.

The optional commands below are manual integration checks, not substitutes for the unit suite:

```powershell
.\.venv\Scripts\python.exe -m chatmpd doctor
.\.venv\Scripts\python.exe -m chatmpd demo
```

`doctor` probes local prerequisites without starting inference. `demo` uses a deterministic scripted model but does invoke the real WSL sandbox unless a test double is supplied.

## Design expectations

Keep changes small and preserve these invariants:

- Inference stays on an explicitly validated loopback HTTP endpoint. Do not silently add a cloud fallback, telemetry, or a paid API.
- The local model and llama.cpp server remain external dependencies; do not bundle multi-gigabyte weights or an opaque server binary into the repository.
- Project paths remain workspace-relative, canonicalized, and protected against traversal, links, junctions, Windows aliases, repository state, and known secret locations.
- Commands are exact argument arrays selected by project profiling. Do not add a shell, arbitrary command execution, package installation, or network-enabled verification.
- Verification runs against a filtered copy, not the live project, in the exact WSL Ubuntu plus bubblewrap boundary.
- A passing check must be newer than the last write before success is accepted.
- Existing files are backed up before replacement, and persisted records should avoid raw source contents and command output.
- ChatMPD may inspect sanitized local Git state, but product code must not fetch, push, commit, create branches, or mutate pull requests/remotes.
- A server process started by ChatMPD must be released reliably. Any pre-existing healthy endpoint must be refused and must not be killed or borrowed as though ChatMPD owned it.
- Game-safe behavior for `eso64.exe` must remain deterministic and covered by tests.

If a proposal intentionally changes one of these boundaries, explain the threat-model impact, add focused negative tests, and update the relevant documentation in the same change.

## Code and documentation style

- Prefer the Python standard library and explicit dependency injection at process, filesystem, network, clock, and UI boundaries.
- Use type hints, small functions, deterministic error messages, bounded reads/outputs, and plain-language GUI text.
- Avoid logging file contents, model conversation contents, command output, credentials, or full remote URLs.
- Add regression tests for both the expected path and important rejection/failure paths.
- Write documentation for the owner first: state the outcome, name prerequisites, include recovery, and avoid guarantees that the implementation cannot make.
- Link to a canonical explanation rather than copying large sections between documents.

## Submitting a change

1. Create a focused branch in your own Git workflow.
2. Make the smallest coherent code, test, and documentation changes.
3. Run focused tests, then the full unit and compile checks above.
4. Review `git diff` for generated files, local paths, secrets, run records, and unrelated edits.
5. Commit with a short description of the behavior changed.
6. Push or open a pull request manually if that is how the repository is hosted.

ChatMPD itself does not push branches or create pull requests; those remain deliberate human actions. In a review, describe user-visible behavior, tests run, security-boundary changes, limitations, and any manual setup needed.

## Security issues and provenance

Do not report a vulnerability in a public change request. Follow [SECURITY.md](SECURITY.md).

Repository history contains an imported Anthropic Claude Code Action snapshot under the MIT License. Preserve applicable copyright and license notices when copying or modifying material from that archive. Anthropic does not maintain ChatMPD; details are in [Third-party notices](THIRD_PARTY_NOTICES.md).
