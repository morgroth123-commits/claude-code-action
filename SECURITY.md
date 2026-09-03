# ChatMPD security policy

ChatMPD is alpha, local-first software that can modify files in a folder selected by the user. Security reports about ChatMPD should go to the current ChatMPD project maintainer—not to Anthropic, Qwen, llama.cpp, Microsoft, Ubuntu, or bubblewrap maintainers unless the issue is independently in their product.

## Reporting a vulnerability

Please use the repository host's private security-advisory feature when one is available. If no private channel is published, contact the current repository maintainer privately before disclosing details. Do not open a public issue containing an exploit, a real credential, a private project file, or a run log with sensitive data.

Include only what is necessary to reproduce the issue:

- the ChatMPD version or commit
- Windows version and whether the app was packaged or run from source
- the affected boundary, such as project path handling, secret filtering, loopback server ownership, run-record persistence, or WSL/bubblewrap command isolation
- a minimal synthetic project and exact reproduction steps
- expected and actual behavior
- impact and any known workaround

Use fake secrets and remove personal paths, model prompts, project source, usernames, and tokens from screenshots and logs. A maintainer can request more information through the private channel.

There is no formal long-term-support schedule yet. Reproduce against the current version when it is safe to do so, and state if an older build is the only affected version you tested.

## Current security posture

The intended task path is local:

- model requests go to a plain-HTTP loopback llama.cpp endpoint only
- no paid or cloud model API is configured
- Git is queried for bounded local context only; ChatMPD does not fetch, push, create a pull request, or otherwise mutate a remote
- verification runs only an exact allowlisted Python command in a filtered, disposable WSL Ubuntu snapshot under bubblewrap with networking unshared
- `.git`, `.chatmpd`, common secret directories, environment files, known credential filenames, and private-key/certificate formats are protected from normal agent access and omitted from verification snapshots
- raw file reads and raw command output are not persisted in run records; eligible originals are backed up before replacement

These are defense-in-depth controls, not a claim of perfect containment or privacy. The Windows application runs with the user's file permissions, the model can make incorrect edits, loopback services can be reached by other software on the same host, filters cannot identify every secret embedded in ordinary source, and the security of Windows, WSL, Ubuntu, bubblewrap, llama.cpp, the model file, and local Git remains part of the overall system.

See [the full security model](docs/security.md) for boundaries, protected paths, residual risks, log contents, and owner guidance.

## Out of scope for a ChatMPD report

The following are not ChatMPD vulnerabilities by themselves:

- a model producing an incorrect answer without crossing a security boundary
- performance limitations caused by the owner's hardware or chosen model
- vulnerabilities in an unmodified external llama.cpp, Qwen, Windows, WSL, Ubuntu, bubblewrap, Python, or Git installation
- a user explicitly placing a secret in task text or an ordinary source file and then asking the model to read that file
- a separately launched service on port `8080`; ChatMPD refuses to take over any already-healthy endpoint, including one that advertises the ChatMPD model alias

If ChatMPD combines an external issue with its own behavior to cross a documented boundary, report the ChatMPD-specific impact privately.

## Disclosure

Please allow reasonable time to investigate and prepare a fix before public disclosure. No bug bounty or payment is promised. Good-faith reports that avoid privacy violations, data destruction, persistence, lateral movement, and service disruption are appreciated.

## Project ownership

ChatMPD is an independent project. Its Git history contains an archived, MIT-licensed Claude Code Action import for provenance, but Anthropic does not maintain ChatMPD and Anthropic's vulnerability-reporting program is not the reporting channel for this project. See [Third-party notices](THIRD_PARTY_NOTICES.md).
