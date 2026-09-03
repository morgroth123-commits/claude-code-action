# Most Effective Use of ChatMPD

ChatMPD works best when you give its local model one small, verifiable result at a time. It is a private task-execution tool for supported Python projects, not a cloud chat service.

## Five-minute first task

1. Back up the project or begin with a clean Git worktree.
2. Open ChatMPD and choose the Python project's actual root folder.
3. Describe one result, its constraints, and the evidence that would count as success.
4. Press Ctrl+Enter once and leave the selected files alone while ChatMPD works.
5. Review the summary, every changed file, every check, and the saved run record.

## A request formula that works

Use: Result + context + constraints + success evidence.

Strong example: "Fix the incorrect total in calculator.py. Keep the public function names and file format unchanged. Add or update standard-library unittest coverage, and finish only when the full unittest suite passes."

Weak example: "Make everything better."

The strong request tells the model where to look, what outcome matters, what it must preserve, and how the application can verify the work. If you know the relevant filename, failing behavior, required compatibility, or exact test, include it. Do not prescribe an implementation you do not actually require; describing the outcome leaves room for the local model to choose the smallest repair.

## Choose the right task size

Describe one bug, one small feature, one focused refactor, or one explanation per run. Split broad work into ordered tasks because the local 7B model and 8,192-token context are intentionally bounded.

Good first tasks include repairing one failing function, adding one validation rule, explaining one unfamiliar module, or updating one focused group of tests. Split a request such as "redesign the application, migrate the database, and deploy it" into independently testable results. Review the first result before asking for the next layer.

## Prepare the project

Use a backed-up local Python project, prefer a clean Git worktree, keep real secrets out of ordinary source text, and confirm WSL Ubuntu plus bubblewrap are ready with doctor when troubleshooting.

Choose the directory that actually contains the Python source and, when present, the `tests` directory. ChatMPD refuses folders with no recognized Python files because it cannot select its fixed offline verification gate. A clean Git worktree makes the result easier to inspect, but ChatMPD does not commit, push, fetch, or open pull requests.

Never put passwords, access tokens, private keys, recovery phrases, or confidential personal data in the task. Known sensitive filenames are filtered, but no filename rule can recognize every secret embedded in ordinary source text.

## While ChatMPD is working

Do not start another ChatMPD window against the same project or edit the same files concurrently. The progress indicator is intentionally indeterminate; local inference can take several minutes.

Keep the application open until it reports completion. ChatMPD blocks window closure while it owns active work so it can finish file and local-model cleanup safely. The interface does not expose an unsafe cancel action. If you are playing ESO, the exact process `eso64.exe` selects the conservative local-model mode described below.

## Review and recover

Inspect the summary, changed paths, checks, and `.chatmpd/runs/<run-id>/run.json`. Use the first-edit backup under that run's `backups/` directory to restore an existing file, and delete unwanted newly created files manually after reviewing them.

**Checks passed** means ChatMPD's fixed command succeeded in the isolated project copy after the last recorded write. It does not prove that every possible behavior is correct. **Checks failed** means the task ended without satisfying that gate; review both the summary and modified files before retrying.

Use **Copy result** to put the nontechnical summary, changed-file list, checks, and record path on the clipboard. Use **Open run folder** to inspect the recovery record. Backups are per run and cover the original version of an eligible existing file the first time ChatMPD replaced it; a newly created file has no earlier version to restore.

## Keyboard and display controls

| Action | Shortcut |
| --- | --- |
| Choose a project | `Ctrl+O` |
| Focus the task composer | `Ctrl+L` |
| Start a permitted task | `Ctrl+Enter` |
| Copy the complete result | `Ctrl+Shift+C` |
| Begin a new task after completion | `Ctrl+N` |
| Increase or decrease text size | `Ctrl++` / `Ctrl+-` |
| Restore 100% application text | `Ctrl+0` |
| Open help | `F1` |
| Close help or return to the composer | `Escape` |

Use Tab and Shift+Tab to move through controls in visual order. Plain Enter adds a new line to the task instead of submitting it. System appearance follows the native Tk/Windows presentation where possible; Light and Dark provide tested custom palettes. Application text size steps from 90% to 160% and combines with Windows display scaling.

Every success, warning, and error includes a text label. Color is additional emphasis, not the only way to understand state.

## Performance while playing ESO

Immediately before starting the model it owns, ChatMPD checks for the exact Windows process name `eso64.exe`. When detected—or when detection cannot complete safely—it runs llama.cpp in CPU-only mode with one inference thread, one batch thread, one parallel request, and Windows IDLE process priority.

This reduces competition with the game but does not eliminate disk, memory, CPU, or WSL activity. Project inventory and snapshot creation still perform disk I/O, and isolated checks can still consume resources. For a large task or the smoothest play session, wait until after ESO is closed.

## Current limits

- Supported projects must contain recognized Python files.
- Verification is fixed to standard-library `unittest` discovery when suitable tests are recognized, otherwise Python `compileall`.
- Model-visible reads, writes, and eligible backups are limited to 256 KiB per file.
- The local model cannot choose an arbitrary shell command.
- Verification runs in an offline WSL/bubblewrap copy, not against the live project.
- ChatMPD does not fetch, push, create a branch, open a pull request, or mutate a remote.
- There is no cloud model fallback, paid API, API key, vendor quota, or per-call fee.
- ChatMPD is alpha software. The local model can misunderstand a request, make an incomplete change, or fail a valid task.

## Troubleshooting

- Use [Windows setup](setup-windows.md) for llama.cpp, the model, WSL Ubuntu, and bubblewrap.
- Use [Troubleshooting and recovery](troubleshooting.md) when doctor reports a missing prerequisite, the model does not start, checks fail, or you need to restore a file.
- Use [Architecture](architecture.md) for the component and data flow.
- Use [Security model](security.md) for enforced boundaries, residual risks, and records.

When asking for help, share the exact non-secret error text, whether `doctor` succeeds, the selected project's general structure, and the run-record path. Remove credentials and confidential source content before sharing anything outside your computer.
