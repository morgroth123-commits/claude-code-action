"""Immutable, dependency-free presentation data for the desktop interface."""

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
    """One human-readable verification result."""

    label: str
    passed: bool


@dataclass(frozen=True)
class TaskPresentation:
    """A stable view of a task outcome, detached from the execution engine."""

    kind: ResultKind
    summary: str
    changed_files: tuple[str, ...] = ()
    checks: tuple[CheckPresentation, ...] = ()
    state_file: Path | None = None


@dataclass(frozen=True)
class ThemePalette:
    """Colors and non-color status labels for one complete UI theme."""

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


_STATUS_LABELS = {
    "neutral": "Ready",
    "working": "Working",
    "success": "Success",
    "warning": "Needs attention",
    "error": "Error",
}

PALETTES: dict[ThemeName, ThemePalette] = {
    "system": ThemePalette(
        canvas="#f3f4f6",
        surface="#ffffff",
        elevated="#ffffff",
        border="#c7cbd1",
        text="#202123",
        muted_text="#50545c",
        accent="#1d4ed8",
        accent_text="#ffffff",
        focus="#1d4ed8",
        success="#047857",
        warning="#92400e",
        error="#b91c1c",
        status_labels=dict(_STATUS_LABELS),
    ),
    "light": ThemePalette(
        canvas="#f7f7f8",
        surface="#ffffff",
        elevated="#ffffff",
        border="#d1d5db",
        text="#1f2937",
        muted_text="#4b5563",
        accent="#1d4ed8",
        accent_text="#ffffff",
        focus="#1d4ed8",
        success="#047857",
        warning="#92400e",
        error="#b91c1c",
        status_labels=dict(_STATUS_LABELS),
    ),
    "dark": ThemePalette(
        canvas="#161719",
        surface="#202123",
        elevated="#2b2c2f",
        border="#4b4d53",
        text="#f4f4f5",
        muted_text="#b7bac0",
        accent="#8aa4ff",
        accent_text="#111827",
        focus="#a7b8ff",
        success="#4ade80",
        warning="#fbbf24",
        error="#f87171",
        status_labels=dict(_STATUS_LABELS),
    ),
}


HELP_TEXT = """Most effective usage

1. Choose the project folder ChatMPD should work in.
2. Describe one concrete outcome and any checks that must pass.
3. Select Start task, review the result, changed files, and checks, then refine.

Keyboard shortcuts
Ctrl+O — Choose project folder
Ctrl+L — Focus the task composer
Ctrl+Enter — Start task
Ctrl+Shift+C — Copy result
Ctrl+N — New task
Ctrl++ — Increase text size
Ctrl+- — Decrease text size
Ctrl+0 — Reset text size
F1 — Open this help
Escape — Close help or return focus to the task

ChatMPD works locally and keeps task execution private to this computer. Do not
enter passwords, API keys, recovery codes, or other secrets in a task."""


def task_byte_usage(task: str) -> tuple[int, int]:
    """Return UTF-8 bytes used and the accepted task limit."""

    return len(str(task).encode("utf-8")), TASK_BYTE_LIMIT


def present_task_outcome(outcome: Any) -> TaskPresentation:
    """Copy an engine outcome into immutable, display-safe presentation data."""

    try:
        result = outcome.result
        status = result.status
        summary = result.summary
        changed_files = result.changed_files
        checks = result.checks
        state_file = result.state_file
    except AttributeError as error:
        raise ValueError("Task outcome is missing required result information.") from error

    normalized_summary = " ".join(str(summary).split())
    if not normalized_summary:
        normalized_summary = "ChatMPD finished without a summary."

    presented_checks = tuple(
        CheckPresentation(
            " ".join(str(part) for part in check.argv),
            check.exit_code == 0,
        )
        for check in checks
    )
    return TaskPresentation(
        kind="success" if status == "succeeded" else "verification_failed",
        summary=normalized_summary,
        changed_files=tuple(str(path) for path in changed_files),
        checks=presented_checks,
        state_file=Path(state_file) if state_file is not None else None,
    )


def present_error(detail: Any) -> TaskPresentation:
    """Convert an exception detail into a bounded, retryable error result."""

    normalized = " ".join(str(detail).split())[:1_000]
    if not normalized:
        normalized = "An unexpected problem stopped ChatMPD."
    return TaskPresentation(kind="error", summary=normalized)


def format_task_presentation(presentation: TaskPresentation) -> str:
    """Format a presentation for copying, logs, and simple text surfaces."""

    sections = [presentation.summary]
    if presentation.changed_files:
        sections.append(
            "Changed files:\n"
            + "\n".join(f"- {path}" for path in presentation.changed_files)
        )
    else:
        sections.append("Changed files:\n- None")

    if presentation.checks:
        sections.append(
            "Checks:\n"
            + "\n".join(
                f"- {'PASSED' if check.passed else 'FAILED'}: {check.label}"
                for check in presentation.checks
            )
        )
    else:
        sections.append("Checks:\n- None recorded")

    if presentation.state_file is not None:
        sections.append(f"Details saved at:\n{presentation.state_file}")
    if presentation.kind == "error":
        sections.append("You can fix the problem and try again.")
    return "\n\n".join(sections)


def palette_for(name: ThemeName) -> ThemePalette:
    """Return a complete palette, rejecting unsupported theme names."""

    try:
        return PALETTES[name]
    except KeyError as error:
        raise ValueError(f"Unsupported theme: {name}") from error


def _relative_luminance(color: str) -> float:
    value = str(color).strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Expected a six-digit hexadecimal color, got {color!r}.")
    try:
        channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    except ValueError as error:
        raise ValueError(f"Expected a hexadecimal color, got {color!r}.") from error
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(foreground: str, background: str) -> float:
    """Return WCAG contrast ratio for two ``#RRGGBB`` colors."""

    first = _relative_luminance(foreground)
    second = _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def step_text_scale(current: int, direction: int) -> int:
    """Move one supported text-size step and clamp at either endpoint."""

    value = int(current)
    if direction > 0:
        return next((step for step in TEXT_SCALE_STEPS if step > value), TEXT_SCALE_STEPS[-1])
    if direction < 0:
        return next(
            (step for step in reversed(TEXT_SCALE_STEPS) if step < value),
            TEXT_SCALE_STEPS[0],
        )
    return min(TEXT_SCALE_STEPS, key=lambda step: abs(step - value))
