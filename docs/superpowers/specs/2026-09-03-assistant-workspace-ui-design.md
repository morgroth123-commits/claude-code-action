# ChatMPD Assistant Workspace UI Design

**Date:** 2026-09-03

**Status:** Approved direction; implementation specification

**Scope:** Replace the current minimal Tk window with an accessible, modern, local assistant workspace without changing ChatMPD's execution authority.

## Context

ChatMPD already has a usable single-task desktop flow: choose a Python project, enter a task, run the local agent in a background thread, and display a text result. Its engine, project preparation, local llama.cpp lifecycle, WSL/bubblewrap verification, recovery records, and command restrictions are separate from the window.

The current interface presents that flow as a vertically stacked form. It does not visually distinguish user intent, work-in-progress state, final response, changed files, verification results, or recovery information. It also lacks a complete keyboard model, appearance controls, explicit focus management, scrollbars, copying/opening actions, and usage guidance.

The redesign will adopt familiar interaction patterns from leading assistant applications without copying their branding or implying capabilities ChatMPD does not have. ChatMPD remains a task-execution platform rather than a generic conversational chatbot.

## Goals

1. Make the first successful task understandable without requiring terminal knowledge.
2. Make the current project, privacy boundary, work state, result, verification result, and recovery path immediately visible.
3. Support complete keyboard operation with a predictable focus order and visible focus state.
4. Remain readable at Windows display scaling and at user-selected larger text sizes.
5. Use status text and icons or shapes in addition to color so meaning never depends on color alone.
6. Preserve safe nonblocking execution and prevent overlapping tasks.
7. Add useful result actions without expanding model or filesystem authority.
8. Add a durable plain-language guide for effective and safe usage.
9. Keep the application free, local-first, and independent of API keys, subscriptions, hosted services, browsers, or paid UI frameworks.

## Non-goals

- Persistent multi-conversation history.
- Token-by-token response streaming.
- Fabricated phase percentages or progress claims not emitted by the engine.
- Arbitrary command entry, terminal emulation, remote repository actions, or cloud synchronization.
- Cancellation that could interrupt file replacement or runtime cleanup unsafely.
- A pixel-for-pixel copy of ChatGPT, Claude, Gemini, or their trademarks.
- Formal certification against every assistive-technology combination in this release.

## Selected approach

Use themed native Tk widgets through `tkinter.ttk`, with a small presentation-model module and no new runtime dependency.

This approach is selected over an embedded web view because it avoids a local HTTP server, browser engine, added network surface, and additional packaging dependency. It is selected over Qt because it keeps the existing Python standard-library distribution model and avoids a much larger executable. A native interface cannot reproduce every animation and rendering detail of a browser application, but it can reproduce the interaction hierarchy that makes those products approachable.

## Product principles

- **Local is visible:** the header always communicates that inference and task execution are local and private by default.
- **One primary action:** the composer has one dominant action, **Start task**, and secondary actions remain visually quieter.
- **Progress is honest:** while a task is running, the interface says that local preparation, planning, editing, and verification may be occurring; it does not claim a specific current phase unless the engine reports one.
- **Results are structured:** summary, file changes, checks, and recovery details are separate readable sections rather than one undifferentiated text block.
- **Safety is legible:** the selected project and verification state are visible before and after execution.
- **Keyboard parity:** every action available with a pointer has a keyboard route.
- **No dead ends:** empty and error states explain the next action the user can take.

## Information architecture

The desktop window has five regions.

### 1. Application header

The header contains:

- ChatMPD name and short descriptor, **Local project assistant**.
- A text badge, **Local · Private**, which does not rely on color alone.
- Appearance control with **System**, **Light**, and **Dark** choices.
- A **Help** action that opens a concise in-app help panel.

The header remains compact and does not imitate another vendor's logo, product name, or account controls.

### 2. Project panel

The left project panel contains:

- A **Project** heading.
- The selected directory's final folder name as the primary label.
- The full canonical path in a selectable read-only field.
- A **Choose project** button.
- A short safety message: ChatMPD can change files in this folder and stores run records under `.chatmpd`.
- A readiness label that shows **Choose a project**, **Project selected**, **Working**, or the last result state.

The panel is approximately 260 logical pixels wide at normal scale. When the window is narrow, it moves above the main workspace rather than clipping essential content.

### 3. Assistant workspace

The main region behaves like a short task timeline:

- The initial state contains a welcome card explaining the three-step flow.
- Starting a task adds a **You asked** card containing the submitted task text.
- The busy state adds a **ChatMPD is working locally** card and an indeterminate progress indicator. The accompanying text explains that the application may be preparing the project, consulting the local model, changing files, and checking a disposable copy.
- Completion replaces the working card with a result card.
- Failed verification uses a warning presentation distinct from an application error.
- Application/runtime errors show a concise explanation and a concrete retry suggestion.

The timeline does not persist across application restarts and does not portray one task as a multi-turn model conversation.

### 4. Task composer

The composer remains anchored at the bottom of the main region and contains:

- A multiline task field with visible label **Describe the result you want**.
- Placeholder guidance when empty: **Example: Fix the failing total calculation and keep public function names unchanged.**
- A live character count against the existing 32 KiB task boundary.
- A short prompt-quality hint: include the desired result, important constraints, and how success should be checked.
- A primary **Start task** button.
- Shortcut text: **Ctrl+Enter to start**.

During execution, the task text remains visible but read-only, the primary action is disabled, and the application does not offer unsafe cancellation. After completion, **New task** clears the timeline and returns focus to the composer while preserving the selected project.

### 5. Status footer

The footer provides a concise textual state such as **Ready**, **Working locally**, **Checks passed**, **Checks failed**, or **Needs attention**. It also contains the current text-size percentage and reinforces that no cloud model is being used.

## Result presentation

The result is represented by immutable presentation data rather than requiring the window to parse a formatted string.

The presentation model contains:

- overall result kind: success, verification failure, or application error;
- final summary;
- changed-file paths;
- check command labels and pass/fail state;
- run-record path when one exists;
- copyable plain-text representation.

The result card contains:

- a status heading with text and visual indicator;
- the final summary;
- an expandable or separately grouped **Changed files** section;
- a **Verification** section with **Passed** or **Failed** text for each check;
- a **Recovery details** section containing the run-record path;
- **Copy result** and **Open run folder** actions;
- **New task** after the worker and runtime cleanup are complete.

Opening the run folder is a direct user action. It opens the containing directory only; it does not execute project content or transmit data.

## State model and transitions

| State | Primary message | Available actions | Focus behavior |
| --- | --- | --- | --- |
| No project | Choose a project to begin | Choose project, Help, appearance | Choose project |
| Ready | Describe the result you want | Edit task, Start task, change project | Composer |
| Invalid task | Describe what ChatMPD should do | Edit task, change project | Composer |
| Working | ChatMPD is working locally | Help and passive viewing only | Status card, without stealing typing focus repeatedly |
| Succeeded | Task finished and checks passed | Copy result, open run folder, new task | Result heading |
| Verification failed | Task finished, but checks did not pass | Copy result, open run folder, new task | Warning heading |
| Application error | ChatMPD could not finish this task | Copy details when present, retry/new task | Error heading |
| Close requested while busy | ChatMPD must finish cleanup before closing | Wait | Status notice |

The controller continues to serialize task execution with its lock and schedules completion rendering on the Tk event loop.

## Accessibility design

### Keyboard

- `Tab` and `Shift+Tab`: traverse interactive controls in visual order.
- `Ctrl+O`: choose a project.
- `Ctrl+L`: focus the task composer.
- `Ctrl+Enter`: start the task when permitted.
- `Ctrl+Shift+C`: copy the complete result without conflicting with ordinary text selection copy.
- `Ctrl+N`: start a new task after completion.
- `Ctrl++` and `Ctrl+-`: increase or decrease interface text size.
- `Ctrl+0`: restore the default text size.
- `F1`: open in-app help.
- `Escape`: close help or return focus to the composer; it never terminates a running task.

The application will not bind ordinary `Enter` to submission because multiline task entry must remain predictable.

### Focus and labels

- Every interactive widget has visible text or a nearby persistent label.
- Grouped controls use labeled frames or headings.
- Disabled controls remain legible.
- A visible focus ring is retained in all custom themes.
- Task validation sends focus to the control that needs correction.
- Completion moves focus once to the result heading or result region; background status animation does not repeatedly steal focus.

### Color and type

- The System mode preserves platform defaults where possible, including high-contrast choices.
- Light and Dark palettes target WCAG 2.2 AA contrast: at least 4.5:1 for normal text and 3:1 for large text and meaningful graphical boundaries.
- Success, warning, and error states include text labels and distinct markers in addition to color.
- Segoe UI is preferred on Windows with a safe Tk fallback.
- Default body text is at least 11 points at 100% application scale.
- User text scaling ranges from 90% to 160% in deterministic steps and combines with Tk/Windows display scaling.

### Assistive technology limits

Native Tk/ttk controls and explicit text labels provide a better basis for Windows assistive technology than canvas-drawn controls. This release will be keyboard-tested and inspected at enlarged scale, but it will not claim formal screen-reader or WCAG certification without testing those specific combinations.

## Appearance system

Presentation constants live outside the Tk layout code:

- spacing scale;
- type scale;
- minimum target sizes;
- semantic colors for canvas, surface, elevated surface, border, text, muted text, focus, accent, success, warning, and error;
- System, Light, and Dark palette selection;
- font scaling.

No essential state is encoded in a color constant. Themes change styling only and never alter application behavior.

The initial appearance follows Windows/Tk system settings. The user can switch modes during a session. Persisting appearance across restarts is deferred unless it can be done without creating another mutable configuration boundary; session-only appearance is sufficient for this release.

## Module boundaries

### `chatmpd/presentation.py`

A new dependency-free module owns:

- semantic UI state enums or literals;
- immutable result/check presentation dataclasses;
- conversion from a task outcome to presentation data;
- plain-text result formatting;
- palette definitions and scale clamping;
- user-facing shortcut and help text constants where appropriate.

This module can be tested without constructing a Tk root.

### `chatmpd/gui.py`

The existing module continues to own:

- `ChatMPDController` background execution and serialization;
- Tk/ttk widget construction;
- keyboard bindings;
- focus management;
- theme application;
- clipboard and run-folder actions;
- rendering snapshots into the five interface regions;
- safe close behavior.

The controller may publish richer immutable snapshots, but its task-runner signature remains `Callable[[Path, str], Any]`.

### Existing engine and runtime modules

`app.py`, `service.py`, `engine.py`, `runtime.py`, `sandbox.py`, and model-provider modules retain their current execution responsibilities. The UI pass does not add tool authority, arbitrary commands, cloud fallback, remote mutation, or a new network listener.

## Error handling

- Empty project and task input are handled before a worker starts.
- Directory chooser cancellation leaves the previous project intact.
- Clipboard and run-folder failures produce nonfatal status messages with the underlying detail bounded and whitespace-normalized.
- Malformed or incomplete outcome data produces a safe application-error presentation rather than crashing the Tk event loop.
- Widget rendering always occurs through the Tk scheduler after background work.
- Closing while busy remains blocked until runtime cleanup is finished.
- The UI never exposes raw secrets intentionally; existing result and task text rules still apply, and the guide tells the user not to enter secrets.

## Most Effective Usage guide

Add `docs/most-effective-usage.md` and link it from the README. It covers:

1. The fastest path to a first successful task.
2. Preparing a small, backed-up Python project.
3. A reusable request formula: desired result, relevant context, constraints, and success criteria.
4. Strong and weak task examples.
5. Choosing task size suitable for a 7B local model and bounded context.
6. Reviewing changed files, checks, and `.chatmpd` recovery records.
7. Recovery after an unwanted change.
8. Performance considerations while ESO is running.
9. Keyboard shortcuts and display adjustments.
10. Troubleshooting links and clear current limitations.

The in-app F1 help panel contains a concise version and points to the bundled/local documentation when available.

## Test-driven implementation

Implementation follows red-green-refactor cycles.

1. Add failing presentation-model tests for structured success, verification failure, errors, plain-text copying, palette completeness, and scale bounds.
2. Implement the smallest presentation module that passes those tests.
3. Add failing controller/window tests for new snapshots and visible interface states.
4. Implement the assistant workspace layout and state rendering.
5. Add failing keyboard/focus/action tests, then implement bindings and focus behavior.
6. Add failing tests for clipboard and run-folder error handling, then implement those actions.
7. Add documentation and packaging assertions for the usage guide.
8. Refactor only while the focused and full suites remain green.

The fake Tk toolkit used by unit tests will be expanded only for behaviors the production window actually uses. Pure formatting and styling logic remains outside Tk so tests validate real behavior rather than an extensive widget mock.

## Verification and release checks

Before the redesigned executable is described as complete:

- run the complete unit-test discovery suite;
- run Python bytecode compilation over production modules;
- run repository whitespace/error checks;
- run the packaging tests;
- rebuild the Windows executable with the repository build script;
- run packaged `doctor` and `demo` smoke checks;
- open the packaged GUI and verify window creation, task entry, keyboard focus, theme switching, text scaling, result actions, and safe close behavior;
- inspect the window at 100% and enlarged application text scale;
- verify the packaged process and any owned local model process are cleaned up;
- record the final executable size and SHA-256 digest.

No remote will be added or pushed as part of this work.

## Acceptance criteria

The redesign is accepted when all of the following are true:

- A first-time user can identify how to choose a project and start a task without opening documentation.
- The interface visually reads as a modern assistant workspace rather than a plain configuration form.
- The submitted task, busy state, final summary, changed files, checks, and recovery location are distinct and readable.
- All primary actions work by keyboard, with documented shortcuts and visible focus.
- Status meaning remains understandable without color.
- Light, Dark, and System modes remain readable, and text can be enlarged without hiding essential controls.
- A running task cannot be started twice or closed before safe cleanup.
- No new cloud, API-key, payment, account, telemetry, or network-listener dependency exists.
- The usage guide is linked from the README and matches the implemented interface.
- The full tests, build, packaged diagnostics, and GUI smoke checks pass with fresh evidence.

## Known trade-offs

- Tk/ttk will not match browser-rendered assistant products pixel for pixel.
- True progress phases require future engine progress events; this pass uses an honest indeterminate state.
- Persistent conversation history and user preferences would create additional data-lifecycle requirements and are intentionally postponed.
- Formal assistive-technology certification requires dedicated testing beyond automated widget and keyboard checks.
