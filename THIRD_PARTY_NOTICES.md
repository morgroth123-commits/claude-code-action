# Third-party notices

This file records ChatMPD's repository provenance and the principal external components used by a normal installation. It does not replace the license text supplied by each component.

## Anthropic Claude Code Action repository snapshot

The ChatMPD Git repository was initialized from a snapshot of Anthropic's **Claude Code Action** project. That imported snapshot is preserved in repository history at the local archival tag:

```text
archive/claude-code-action-import
```

The archived material is:

```text
Copyright (c) 2025 Anthropic, PBC
Licensed under the MIT License
```

The complete MIT permission notice and warranty disclaimer are retained in [LICENSE](LICENSE). In a clone containing the archive tag, the original archived license can also be inspected locally with:

```powershell
git show archive/claude-code-action-import:LICENSE
```

The legacy action scaffold has been removed from the current ChatMPD product. The archive remains for license compliance and historical provenance. **Anthropic does not maintain, sponsor, endorse, or provide support for ChatMPD.** ChatMPD security reports must follow [ChatMPD's security policy](SECURITY.md), not Anthropic's reporting program.

The upstream project associated with the imported snapshot is [anthropics/claude-code-action](https://github.com/anthropics/claude-code-action). That link identifies provenance; it does not imply compatibility or an ongoing relationship.

## External local-inference components

ChatMPD discovers and uses the following components when they are installed by the owner. They are **not bundled** in this repository or by `ChatMPD.spec`:

### llama.cpp

- Purpose: provides the local `llama-server.exe` inference process.
- Project: [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)
- License information: [llama.cpp LICENSE](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE)

### Qwen2.5-Coder-7B-Instruct GGUF

- Purpose: provides the local coding-model weights, with ChatMPD discovering the `Q4_K_M` quantization.
- Model repository: [Qwen/Qwen2.5-Coder-7B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF)
- License and model terms: review the license and model card in that repository before downloading or redistributing weights.

Model files can be several gigabytes. They remain separate downloads governed by their own terms. ChatMPD's MIT License does not relicense the weights or llama.cpp.

## External isolation and operating-system components

Verification depends on components installed and maintained outside ChatMPD:

- [Windows Subsystem for Linux](https://learn.microsoft.com/windows/wsl/install), supplied under Microsoft's applicable terms
- an Ubuntu WSL distribution, supplied under Ubuntu and individual package terms
- [bubblewrap](https://github.com/containers/bubblewrap), installed from Ubuntu's package repository and governed by its own license
- the Ubuntu Python interpreter and base utilities used inside the isolated snapshot

These system components are prerequisites, not ChatMPD distributions. Their presence does not make Microsoft, Canonical, bubblewrap maintainers, or Python maintainers responsible for ChatMPD.

## Python and packaged builds

ChatMPD source code requires Python 3.11 or newer and is licensed separately from Python itself. A Windows executable produced from `ChatMPD.spec` uses [PyInstaller](https://pyinstaller.org/) and may contain redistributable Python, Tcl/Tk, and PyInstaller bootloader components. Anyone distributing a packaged executable is responsible for preserving all notices required by the exact Python, Tcl/Tk, PyInstaller, and other build components they ship.

This repository's optional build dependency is declared in `pyproject.toml`; downloaded build tools are not checked into the source tree.

## Trademarks and project independence

Names such as Anthropic, Claude, Qwen, llama.cpp, Microsoft, Windows, Ubuntu, Python, and PyInstaller belong to their respective owners. They are used here only to identify provenance, compatibility, or prerequisites. ChatMPD is an independent project.
