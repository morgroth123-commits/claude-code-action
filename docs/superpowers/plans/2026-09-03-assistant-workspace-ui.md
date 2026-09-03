# ChatMPD Assistant Workspace UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ChatMPD's minimal task form with a modern, accessible, assistant-style Windows workspace and add a practical guide for effective use.

**Architecture:** Keep the local task engine and `Callable[[Path, str], Any]` runner boundary unchanged. Add a dependency-free presentation module for immutable result data, themes, scaling, and help text; keep Tk/ttk construction, controller scheduling, keyboard bindings, and user-triggered desktop actions in `chatmpd/gui.py`.

**Tech Stack:** Python 3.11+, standard-library `tkinter`/`ttk`, `unittest`, PyInstaller 6, PowerShell, Windows 11.

**Spec:** `docs/superpowers/specs/2026-09-03-assistant-workspace-ui-design.md`

## Global Constraints

- Add no paid API, per-call fee, API key, account, subscription, telemetry, browser runtime, hosted service, or cloud model dependency.
- Add no Python runtime dependency; `[project].dependencies` must remain empty.
- Preserve `run_local_task(workspace: Path, task: str)` and the existing engine, project-preparation, local llama.cpp, WSL/bubblewrap, and recovery boundaries.
- Do not add arbitrary command entry, remote Git mutation, network listeners, pretend streaming, fabricated progress percentages, or unsafe cancellation.
- Use native text or native widgets for all meaningful content; never encode status by color alone.
- Target at least 4.5:1 contrast for normal text and 3:1 for large text and meaningful graphical boundaries in custom Light and Dark palettes.
- Support System, Light, and Dark appearance modes and deterministic application text scaling from 90% through 160%.
- Preserve background execution, single-task serialization, Tk-thread scheduling, and safe close blocking while busy.
- Keep prompt text at the existing 32 KiB UTF-8 boundary and never put real credentials or secrets in fixtures, guides, or logs.
- Follow red-green-refactor for every production behavior change and run fresh full verification before completion claims.
- Do not add, push, or mutate a Git remote.

---

## File map

### Create

- `chatmpd/presentation.py`: immutable UI result data, safe outcome conversion, plain-text formatting, task-byte accounting, theme palettes, contrast calculation, text-scale stepping, and built-in help text.
- `tests/test_presentation.py`: direct tests for every presentation and appearance rule without constructing Tk.
- `docs/most-effective-usage.md`: plain-language first-run, prompting, safety, recovery, performance, accessibility, and troubleshooting guide.

### Modify

- `chatmpd/gui.py`: richer controller snapshots, Tk/ttk adapter, assistant workspace layout, responsive arrangement, state rendering, shortcuts, focus, themes, scaling, clipboard, help, and run-folder actions.
- `tests/test_gui.py`: structured controller assertions plus a richer fake Tk toolkit for real window behavior tests.
- `tests/test_packaging.py`: assert that the usage guide is copied beside the executable and no dependency is added.
- `README.md`: link the usage guide, update screenshots-free UI instructions, and correct the preflight/runtime order.
- `docs/architecture.md`: align the desktop data flow with preflight-before-runtime behavior and the presentation module.
- `docs/security.md`: describe the host snapshot as an OS-backed temporary file rather than guaranteed in-memory storage.
- `scripts/build-windows.ps1`: copy the guide to `dist\Most Effective Usage.md` after a successful build.

### Preserve without behavioral modification

- `chatmpd/app.py`
- `chatmpd/service.py`
- `chatmpd/engine.py`
- `chatmpd/project.py`
- `chatmpd/runtime.py`
- `chatmpd/sandbox.py`
- `chatmpd/llamacpp.py`
- `ChatMPD.spec`

---

### Task 0: Commit the verified recovered application baseline

**Files:**

- Commit: all existing recovered application, test, documentation, license, and legacy-removal changes already present before this UI plan
- Exclude: generated `.venv/`, `build/`, `dist/`, caches, logs, and model files through the existing `.gitignore`

**Interfaces:**

- Consumes: recovered working tree whose current executable already launches
- Produces: a clean Git baseline so each UI red-green cycle has an inspectable diff

- [ ] **Step 1: Re-run the recovered baseline unit suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: 122 tests run and all pass. If the discovered count differs, inspect the test list and record the exact legitimate count before continuing.

- [ ] **Step 2: Re-run source compilation and repository checks**

Run:

```powershell
.\.venv\Scripts\python.exe -m compileall -q chatmpd chatmpd_launcher.py
git diff --check
```

Expected: both commands exit `0` with no syntax or whitespace error.

- [ ] **Step 3: Stage the recovered tree and inspect the exact commit**

Run:

```powershell
git add -A
git diff --cached --check
git diff --cached --stat
git status --short
```

Expected: the staged tree removes the imported Claude GitHub Action application, adds the Python ChatMPD application/tests/docs, and does not include generated artifacts or files outside the repository.

- [ ] **Step 4: Commit the baseline**

Run:

```powershell
git commit -m "Recover local-first ChatMPD application"
```

Expected: one local commit on `chatmpd/recovery`; no push and no upstream configuration.

---

### Task 1: Add dependency-free presentation models and appearance primitives

**Files:**

- Create: `chatmpd/presentation.py`
- Create: `tests/test_presentation.py`

**Interfaces:**

- Consumes: task outcomes shaped as `outcome.result.status`, `.summary`, `.changed_files`, `.checks`, and `.state_file`
- Produces: `CheckPresentation`, `TaskPresentation`, `ThemePalette`, `present_task_outcome()`, `present_error()`, `format_task_presentation()`, `task_byte_usage()`, `contrast_ratio()`, `palette_for()`, and `step_text_scale()`

- [ ] **Step 1: Write failing result-presentation tests**

Create `tests/test_presentation.py` with these exact initial imports and focused tests:

```python
from pathlib import Path
from types import SimpleNamespace
import unittest

from chatmpd.presentation import (
    CheckPresentation,
    TaskPresentation,
    format_task_presentation,
    present_error,
    present_task_outcome,
    task_byte_usage,
)


class ResultPresentationTest(unittest.TestCase):
    def test_success_preserves_summary_files_checks_and_state_path(self) -> None:
        outcome = SimpleNamespace(
            result=SimpleNamespace(
                status="succeeded",
                summary="Repaired the calculator.",
                changed_files=["calculator.py"],
                checks=[SimpleNamespace(argv=["python", "-m", "unittest"], exit_code=0)],
                state_file=Path("C:/project/.chatmpd/runs/1/run.json"),
            )
        )

        result = present_task_outcome(outcome)

        self.assertEqual(result.kind, "success")
        self.assertEqual(result.summary, "Repaired the calculator.")
        self.assertEqual(result.changed_files, ("calculator.py",))
        self.assertEqual(result.checks, (CheckPresentation("python -m unittest", True),))
        self.assertEqual(result.state_file, Path("C:/project/.chatmpd/runs/1/run.json"))

    def test_failed_check_uses_verification_failure_kind(self) -> None:
        outcome = SimpleNamespace(
            result=SimpleNamespace(
                status="failed",
                summary="The repair did not pass.",
                changed_files=[],
                checks=[SimpleNamespace(argv=["python", "-m", "unittest"], exit_code=1)],
                state_file=Path("C:/project/.chatmpd/runs/2/run.json"),
            )
        )

        result = present_task_outcome(outcome)

        self.assertEqual(result.kind, "verification_failed")
        self.assertFalse(result.checks[0].passed)
        self.assertIn("FAILED: python -m unittest", format_task_presentation(result))

    def test_error_detail_is_flattened_bounded_and_retryable(self) -> None:
        result = present_error("local model\nnot ready")
        self.assertEqual(result.kind, "error")
        self.assertEqual(result.summary, "local model not ready")
        self.assertIn("fix the problem and try again", format_task_presentation(result).lower())

    def test_task_usage_counts_utf8_bytes(self) -> None:
        self.assertEqual(task_byte_usage("Aé"), (3, 32_768))
```

- [ ] **Step 2: Run the result tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_presentation.ResultPresentationTest -v
```

Expected: import failure because `chatmpd.presentation` does not exist.

- [ ] **Step 3: Implement the immutable result model**

Create `chatmpd/presentation.py` with these public types and signatures:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ResultKind = Literal["success", "verification_failed", "error"]
ThemeName = Literal["system", "light", "dark"]
UiTone = Literal["neutral", "working", "success", "warning", "error"]
TASK_BYTE_LIMIT = 32_768
TEXT_SCALE_STEPS = (90, 100, 110, 125, 140, 160)


@dataclass(frozen=True)
class CheckPresentation:
    label: str
    passed: bool


@dataclass(frozen=True)
class TaskPresentation:
    kind: ResultKind
    summary: str
    changed_files: tuple[str, ...] = ()
    checks: tuple[CheckPresentation, ...] = ()
    state_file: Path | None = None


def task_byte_usage(task: str) -> tuple[int, int]:
    return len(str(task).encode("utf-8")), TASK_BYTE_LIMIT
```

Implement `present_task_outcome(outcome)` by validating the required result attributes, normalizing whitespace only in the summary, copying paths/check labels into immutable tuples, and selecting `success` only for status `succeeded`. Implement `present_error(detail)` with a whitespace-flattened maximum of 1,000 characters and a nonempty fallback. Implement `format_task_presentation()` with the existing headings `Changed files`, `Checks`, and `Details saved at` so CLI/window wording remains compatible.

- [ ] **Step 4: Run the result tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_presentation.ResultPresentationTest -v
```

Expected: all result-presentation tests pass.

- [ ] **Step 5: Write failing palette, contrast, and scale tests**

Add these exact palette and scale assertions:

```python
from chatmpd.presentation import (
    PALETTES,
    contrast_ratio,
    palette_for,
    step_text_scale,
)


class AppearancePresentationTest(unittest.TestCase):
    def test_custom_palettes_meet_text_contrast_target(self) -> None:
        for name in ("light", "dark"):
            palette = palette_for(name)
            self.assertGreaterEqual(contrast_ratio(palette.text, palette.canvas), 4.5)
            self.assertGreaterEqual(contrast_ratio(palette.muted_text, palette.surface), 4.5)

    def test_every_palette_contains_semantic_non_color_labels(self) -> None:
        self.assertEqual(set(PALETTES), {"system", "light", "dark"})
        for palette in PALETTES.values():
            self.assertTrue(palette.status_labels["success"])
            self.assertTrue(palette.status_labels["warning"])
            self.assertTrue(palette.status_labels["error"])

    def test_text_scale_steps_are_bounded(self) -> None:
        self.assertEqual(step_text_scale(100, 1), 110)
        self.assertEqual(step_text_scale(100, -1), 90)
        self.assertEqual(step_text_scale(160, 1), 160)
        self.assertEqual(step_text_scale(90, -1), 90)
```

- [ ] **Step 6: Run the appearance tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_presentation.AppearancePresentationTest -v
```

Expected: failure because palette and scaling APIs are not defined.

- [ ] **Step 7: Implement appearance primitives and built-in help**

Add:

```python
@dataclass(frozen=True)
class ThemePalette:
    canvas: str
    surface: str
    elevated: str
    border: str
    text: str
    muted_text: str
    accent: str
    accent_text: str
    focus: str
    success: str
    warning: str
    error: str
    status_labels: dict[str, str]
```

Define complete `system`, `light`, and `dark` palettes. Implement hexadecimal relative luminance and `contrast_ratio(foreground, background)` according to the sRGB contrast formula. Implement `step_text_scale(current, direction)` by moving through `TEXT_SCALE_STEPS` and clamping at the endpoints. Add `HELP_TEXT` containing the three-step task flow, every keyboard shortcut, the local/private statement, and the instruction not to enter secrets.

- [ ] **Step 8: Run presentation tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_presentation -v
git diff --check -- chatmpd/presentation.py tests/test_presentation.py
git add chatmpd/presentation.py tests/test_presentation.py
git commit -m "Add accessible UI presentation model"
```

Expected: focused tests pass and the commit contains only the presentation module and its tests.

---

### Task 2: Publish structured controller snapshots

**Files:**

- Modify: `chatmpd/gui.py`
- Modify: `tests/test_gui.py`

**Interfaces:**

- Consumes: `present_task_outcome()`, `present_error()`, and `format_task_presentation()` from Task 1
- Produces: `UiSnapshot(busy, status, tone, result, start_enabled, submitted_task)` and unchanged `ChatMPDController.start(workspace, task) -> bool`

- [ ] **Step 1: Convert controller expectations to structured failing tests**

Update the success test to require:

```python
self.assertEqual(snapshots[-1].tone, "working")
self.assertEqual(snapshots[-1].submitted_task, "Repair the calculator")
self.assertIsNone(snapshots[-1].result)

# after scheduled completion
self.assertEqual(snapshots[-1].tone, "success")
self.assertEqual(snapshots[-1].result.kind, "success")
self.assertEqual(snapshots[-1].result.changed_files, ("calculator.py",))
```

Update the verification-failure test to require tone `warning` and result kind `verification_failed`. Update the exception test to require tone `error`, result kind `error`, and the normalized retryable summary. Keep the missing-workspace, blank-task, duplicate-start, scheduling, and safe-close assertions.

- [ ] **Step 2: Run controller tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_gui.ChatMPDControllerTest -v
```

Expected: failures because the existing `UiSnapshot` has no `tone`, structured result, or submitted task.

- [ ] **Step 3: Implement the structured snapshot contract**

Change `UiSnapshot` to:

```python
@dataclass(frozen=True)
class UiSnapshot:
    busy: bool
    status: str
    tone: UiTone
    result: TaskPresentation | None
    start_enabled: bool
    submitted_task: str = ""
```

Publish these exact state mappings:

| Event | Status | Tone | Result |
| --- | --- | --- | --- |
| Missing project | `Choose a project folder first.` | `warning` | `None` |
| Blank task | `Describe what you want ChatMPD to do.` | `warning` | `None` |
| Duplicate start | `ChatMPD is already working on a task.` | `working` | `None` |
| Accepted start | `ChatMPD is working locally...` | `working` | `None` |
| Success | `Task finished successfully.` | `success` | structured success |
| Failed verification | `Task finished, but its checks did not pass.` | `warning` | structured verification failure |
| Exception | `ChatMPD could not finish this task.` | `error` | structured error |

Keep the current lock and scheduler placement. Keep `format_task_outcome(outcome)` as a compatibility wrapper that returns `format_task_presentation(present_task_outcome(outcome))`.

- [ ] **Step 4: Run controller and formatting tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_gui.ChatMPDControllerTest tests.test_gui.TaskOutcomeFormattingTest -v
```

Expected: all targeted tests pass.

- [ ] **Step 5: Commit the controller state change**

Run:

```powershell
git diff --check -- chatmpd/gui.py tests/test_gui.py
git add chatmpd/gui.py tests/test_gui.py
git commit -m "Structure desktop task state"
```

Expected: the commit contains only the snapshot/controller transition and compatible tests, not the final visual layout.

---

### Task 3: Build the assistant workspace shell and responsive task timeline

**Files:**

- Modify: `chatmpd/gui.py`
- Modify: `tests/test_gui.py`

**Interfaces:**

- Consumes: structured `UiSnapshot`, `TaskPresentation`, `palette_for()`, and task runner from earlier tasks
- Produces: header, project panel, timeline, composer, action row, progress indicator, and status footer through `ChatMPDWindow`

- [ ] **Step 1: Expand the fake toolkit only for required native behavior**

Extend `FakeWidget` with recorded `grid()`, `grid_configure()`, `pack_forget()`, `grid_remove()`, `bind()`, `focus_set()`, `tag_configure()`, `see()`, `start()`, and `stop()` calls. Extend `FakeToolkit` with `LabelFrame`, `Scrollbar`, `Progressbar`, `Combobox`, `Separator`, and `Style`. Extend `FakeRoot` with `geometry()`, `configure()`, `bind()`, `columnconfigure()`, `rowconfigure()`, `clipboard_clear()`, `clipboard_append()`, `focus_get()`, and a fake `tk.call()` scaling value.

Store enough state for assertions; do not implement an independent layout engine in the fake.

- [ ] **Step 2: Write failing shell and state-rendering tests**

Add window tests that require:

```python
self.assertEqual(root.window_title, "ChatMPD — Local project assistant")
toolkit.find("Label", "Local · Private")
toolkit.find("Button", "Choose project")
toolkit.find("Button", "Start task")
toolkit.find("Button", "Help")
self.assertIn("Describe the result you want", toolkit.label_texts())
self.assertIn("No cloud model", toolkit.label_texts())
```

Start a controlled background task and assert that the timeline contains `YOU ASKED`, the submitted text, and `CHATMPD IS WORKING LOCALLY`; assert that the progress indicator starts and the start button is disabled. Complete it and assert that the timeline contains `CHECKS PASSED`, `CHANGED FILES`, `calculator.py`, `VERIFICATION`, and the run-record path; assert that progress stops and result actions become enabled.

- [ ] **Step 3: Run the window tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_gui.ChatMPDWindowTest -v
```

Expected: failures for missing assistant-shell controls and toolkit behavior.

- [ ] **Step 4: Add a production Tk/ttk adapter**

Create a private adapter when `toolkit is None`:

```python
def _load_toolkit() -> Any:
    import tkinter as tk
    from tkinter import ttk

    return SimpleNamespace(
        StringVar=tk.StringVar,
        Frame=ttk.Frame,
        LabelFrame=ttk.LabelFrame,
        Label=ttk.Label,
        Entry=ttk.Entry,
        Button=ttk.Button,
        Combobox=ttk.Combobox,
        Progressbar=ttk.Progressbar,
        Scrollbar=ttk.Scrollbar,
        Separator=ttk.Separator,
        Style=ttk.Style,
        Text=tk.Text,
    )
```

Continue accepting the injected `FakeToolkit`. Keep directory chooser, help, and desktop-open callables injectable so tests never open real dialogs or processes.

- [ ] **Step 5: Construct the five-region assistant workspace**

Split construction into private methods `_build_header()`, `_build_project_panel()`, `_build_timeline()`, `_build_composer()`, and `_build_footer()` so `__init__` only initializes state and wires sections.

Use a root size near `1100x760` and minimum `780x640`. Use `grid` for the body: project panel at column `0`, main workspace at column `1`, main column weight `1`. Bind root configure events and switch to the stacked layout when width is below `900` logical pixels. Store the last compact/wide state and do not redo grid work when it has not changed.

Use a read-only `Text` timeline with a vertical scrollbar and tags for headings, user content, assistant content, success, warning, error, and muted metadata. Keep result actions outside the `Text` widget as real buttons. Use an indeterminate `Progressbar`; start it only for `tone == "working"` and stop it for every other render.

- [ ] **Step 6: Render every snapshot state without invented progress**

Implement `_render(snapshot)` to:

1. update textual status and project readiness;
2. disable project/task/start controls while busy;
3. show the submitted task once under `YOU ASKED`;
4. render the honest working copy while busy;
5. render structured summary, file changes, verification labels, and recovery path on completion;
6. enable copy/open/new-task actions only when their required data exists;
7. never display a percentage or phase not present in `UiSnapshot`.

- [ ] **Step 7: Run window and complete GUI tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_gui.ChatMPDWindowTest -v
.\.venv\Scripts\python.exe -m unittest tests.test_gui -v
```

Expected: all GUI tests pass and controller background scheduling remains covered.

- [ ] **Step 8: Commit the assistant shell**

Run:

```powershell
git diff --check -- chatmpd/gui.py tests/test_gui.py
git add chatmpd/gui.py tests/test_gui.py
git commit -m "Build assistant workspace desktop shell"
```

---

### Task 4: Add accessibility shortcuts, focus behavior, themes, scaling, and result actions

**Files:**

- Modify: `chatmpd/gui.py`
- Modify: `tests/test_gui.py`

**Interfaces:**

- Consumes: assistant shell and appearance primitives
- Produces: `_bind_shortcuts()`, `_apply_theme()`, `_change_text_scale()`, `_copy_result()`, `_open_run_folder()`, `_show_help()`, and `_new_task()` window behavior

- [ ] **Step 1: Write failing keyboard and focus tests**

Require root bindings for:

```text
<Control-o>
<Control-l>
<Control-Return>
<Control-Shift-C>
<Control-n>
<Control-plus>
<Control-equal>
<Control-minus>
<Control-0>
<F1>
<Escape>
```

Assert that `Ctrl+L` focuses the composer, `Ctrl+Enter` calls start once, input validation returns focus to the missing project or task control, successful completion focuses the result region once, and changing a background status does not repeatedly steal focus.

- [ ] **Step 2: Run keyboard tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_gui.ChatMPDWindowAccessibilityTest -v
```

Expected: failure because shortcuts and focus routing are absent.

- [ ] **Step 3: Implement shortcuts and deterministic focus routing**

Bind each shortcut to a method returning the Tk string `"break"`. Do not bind plain Enter. Set `takefocus=True` on every pointer-action control and preserve the visual order: theme, Help, project chooser, project path, task composer, Start, timeline, result actions, footer controls.

On invalid project, focus **Choose project**. On invalid task, focus the composer after removing placeholder text. On completion, call `focus_set()` and `see("end")` on the result timeline only once. `Escape` closes help if a help surface is open; otherwise it focuses the composer and never cancels work.

- [ ] **Step 4: Write failing theme and scaling tests**

Assert that System, Light, and Dark can be selected, invalid theme names fall back to System, all custom `Text` colors come from the selected palette, text scale steps follow `(90, 100, 110, 125, 140, 160)`, and `Ctrl+0` restores `100`.

- [ ] **Step 5: Run theme tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_gui.ChatMPDWindowAppearanceTest -v
```

Expected: failure because the shell has no theme/scaling implementation.

- [ ] **Step 6: Implement theme and scale application**

Use `ttk.Style.configure()` and `Style.map()` for named frame, label, card, button, entry, combobox, and progress styles. Apply palette colors directly to native `Text` widgets and their tags. Keep an explicit high-visibility focus style. Store the Tk base scaling once and apply `base_scaling * text_scale / 100` through `root.tk.call("tk", "scaling", value)`.

System mode must use the native ttk theme where feasible and fall back to the system palette constants for `Text`. Light and Dark modes must use only the tested palette values.

- [ ] **Step 7: Write failing result-action and help tests**

Add tests that:

- copy a completed result and assert the fake root clipboard equals `format_task_presentation(result)`;
- call **Open run folder** and assert the injected opener receives `result.state_file.parent` exactly;
- reject an absent or escaping/nonexistent state path with a bounded nonfatal status instead of launching anything;
- call Help/F1 and assert the injected help presenter receives title `ChatMPD Help` and `HELP_TEXT`;
- call **New task** and assert the project remains selected, the task/timeline clear, and the composer gains focus;
- simulate clipboard/opener exceptions and assert status becomes `Needs attention` without crashing.

- [ ] **Step 8: Run action tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_gui.ChatMPDWindowActionTest -v
```

Expected: failure because the actions are absent.

- [ ] **Step 9: Implement safe user-triggered actions and help**

Default help presentation uses `tkinter.messagebox.showinfo(parent=root, title="ChatMPD Help", message=HELP_TEXT)`. Default run-folder opening uses `os.startfile(str(directory))` only after confirming the presentation contains a state file, resolving its parent, and confirming it is a directory. Copying writes only the formatted completed result to the clipboard. Normalize and bound desktop-action errors before putting them in status text.

Implement placeholder behavior with a dedicated boolean so the example is never submitted as task text. Update the UTF-8 byte counter on `<<Modified>>` or key events, and show `used / 32,768 bytes`; use explicit warning text when the limit is exceeded.

- [ ] **Step 10: Run all GUI and presentation tests and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_presentation tests.test_gui -v
git diff --check -- chatmpd/gui.py tests/test_gui.py
git add chatmpd/gui.py tests/test_gui.py
git commit -m "Add accessible desktop interactions"
```

Expected: all targeted tests pass with no real dialog, clipboard, directory chooser, or external process invoked by tests.

---

### Task 5: Add the Most Effective Usage guide and align user documentation

**Files:**

- Create: `docs/most-effective-usage.md`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/security.md`
- Modify: `scripts/build-windows.ps1`
- Modify: `tests/test_packaging.py`

**Interfaces:**

- Consumes: implemented labels, shortcuts, result actions, current local runtime behavior, and build output
- Produces: accurate user guidance in the repository and `dist\Most Effective Usage.md`

- [ ] **Step 1: Write failing documentation/packaging assertions**

Extend `tests/test_packaging.py` with:

```python
def test_build_copies_the_usage_guide_beside_the_executable(self) -> None:
    root = Path(__file__).resolve().parents[1]
    guide = (root / "docs" / "most-effective-usage.md").read_text(encoding="utf-8")
    build = (root / "scripts" / "build-windows.ps1").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    self.assertIn("# Most Effective Use of ChatMPD", guide)
    self.assertIn("Ctrl+Enter", guide)
    self.assertIn("Never put passwords", guide)
    self.assertIn("Most Effective Usage.md", build)
    self.assertIn("docs/most-effective-usage.md", readme)
```

Add an assertion that `pyproject.toml` still has `dependencies = []`.

- [ ] **Step 2: Run packaging tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_packaging -v
```

Expected: failure because the guide and copy command do not exist.

- [ ] **Step 3: Write the complete usage guide**

Create `docs/most-effective-usage.md` from this complete copy, updating a shortcut label only if the implemented accessible label differs:

```markdown
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
```

- [ ] **Step 4: Update README and correct documentation drift**

Add the guide to the README documentation list and update Quick Start button names to **Choose project** and **Start task**. In `README.md` and `docs/architecture.md`, state that `prepare_project_task()` completes before entering `LlamaCppRuntime`. In `docs/security.md`, replace any guarantee that the host tar is in memory with the accurate statement that `tempfile.TemporaryFile` is OS-backed and may use memory or disk according to the host.

- [ ] **Step 5: Copy the guide after each successful Windows build**

After confirming `dist\ChatMPD.exe` exists, add:

```powershell
$sourceGuide = Join-Path $repository "docs\most-effective-usage.md"
$distGuide = Join-Path $repository "dist\Most Effective Usage.md"
Copy-Item -LiteralPath $sourceGuide -Destination $distGuide -Force
```

Print both artifact paths without printing environment variables or unrelated files.

- [ ] **Step 6: Run packaging/doc checks and commit**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_packaging tests.test_package_metadata -v
git diff --check -- README.md docs scripts/build-windows.ps1 tests/test_packaging.py
rg -n "Start ChatMPD|GUI task path acquires this runtime before project profiling|in-memory" README.md docs
```

Expected: tests pass, whitespace check passes, and the stale phrases have no inaccurate matches. Review any legitimate contextual `in-memory` match rather than deleting it automatically.

Run:

```powershell
git add README.md docs/most-effective-usage.md docs/architecture.md docs/security.md scripts/build-windows.ps1 tests/test_packaging.py
git commit -m "Document effective ChatMPD usage"
```

---

### Task 6: Run full release verification and rebuild the Windows application

**Files:**

- Verify: all tracked source, tests, documentation, and build definition
- Generate: ignored `build/`, `dist/ChatMPD.exe`, and `dist/Most Effective Usage.md`
- Preserve: no Git remote mutation and no secret-bearing output

**Interfaces:**

- Consumes: all earlier task commits
- Produces: verified local Windows executable, adjacent usage guide, digest, and clean tracked tree

- [ ] **Step 1: Run the complete test and compilation gates**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q chatmpd chatmpd_launcher.py
git diff --check
```

Expected: every discovered test passes, compilation exits `0`, and Git reports no whitespace error. Record the exact final test count rather than assuming 122 after new tests are added.

- [ ] **Step 2: Rebuild from the repository script**

Run:

```powershell
.\scripts\build-windows.ps1
```

Expected: PyInstaller exits `0`, `dist\ChatMPD.exe` exists, `dist\Most Effective Usage.md` exists, and the script prints the executable's SHA-256 digest.

- [ ] **Step 3: Run packaged diagnostics without a terminal window dependency**

Run each process separately and record its exit code:

```powershell
$doctor = Start-Process -FilePath ".\dist\ChatMPD.exe" -ArgumentList "doctor" -Wait -PassThru -WindowStyle Hidden
$doctor.ExitCode
```

```powershell
$demo = Start-Process -FilePath ".\dist\ChatMPD.exe" -ArgumentList "demo" -Wait -PassThru -WindowStyle Hidden
$demo.ExitCode
```

Expected: both exit `0`; the demo uses fake project content and the deterministic scripted model, not the GGUF.

- [ ] **Step 4: Inspect the packaged GUI**

Open `dist\ChatMPD.exe` visibly. Verify:

- window title and five-region layout;
- System, Light, and Dark appearance choices;
- 100%, 125%, and 160% application text scale without clipped primary actions;
- Tab/Shift+Tab order and visible focus;
- `Ctrl+O`, `Ctrl+L`, `Ctrl+Enter`, text-scale shortcuts, `F1`, and Escape behavior;
- project chooser cancellation preserves the prior project;
- working state disables overlapping starts and safe close remains blocked;
- success and failed-check sample states are covered by automated tests and the packaged GUI can show the welcome/ready states;
- Help text contains every shortcut and local/private guidance.

Close the idle GUI and confirm no `ChatMPD.exe` or owned `llama-server.exe` process from the smoke check remains.

- [ ] **Step 5: Record final artifacts and repository state**

Run:

```powershell
Get-Item -LiteralPath ".\dist\ChatMPD.exe", ".\dist\Most Effective Usage.md" | Select-Object FullName, Length, LastWriteTimeUtc
Get-FileHash -LiteralPath ".\dist\ChatMPD.exe" -Algorithm SHA256
git status --short
git log --oneline --decorate -8
git remote -v
```

Expected: tracked tree is clean, ignored artifacts exist, the local task commits are visible on `chatmpd/recovery`, and no new remote or upstream was added.

- [ ] **Step 6: Present the result without overstating it**

Report the clickable executable and guide paths, exact test count, build result, packaged diagnostic exit codes, GUI checks performed, SHA-256 digest, branch/commit, and remaining limitations. State that the executable is unsigned and may trigger SmartScreen. Keep the completed security review's two low findings separate from the UI result; do not call them fixed unless a separate tested remediation is requested and completed.
