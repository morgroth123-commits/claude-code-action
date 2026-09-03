"""A small desktop interface for running ChatMPD project tasks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, Thread
from types import SimpleNamespace
from typing import Any, Callable

from chatmpd.presentation import (
    HELP_TEXT,
    TaskPresentation,
    UiTone,
    format_task_presentation,
    palette_for,
    present_error,
    present_task_outcome,
    step_text_scale,
    task_byte_usage,
)


@dataclass(frozen=True)
class UiSnapshot:
    """Everything the window needs to display at a point in time."""

    busy: bool
    status: str
    tone: UiTone
    result: TaskPresentation | None
    start_enabled: bool
    submitted_task: str = ""


class ChatMPDController:
    """Run a supplied ChatMPD task without blocking the desktop window."""

    def __init__(
        self,
        *,
        task_runner: Callable[[Path, str], Any],
        schedule: Callable[[Callable[[], None]], None],
        publish: Callable[[UiSnapshot], None],
    ) -> None:
        self._task_runner = task_runner
        self._schedule = schedule
        self._publish = publish
        self._lock = Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def start(self, workspace: str, task: str) -> bool:
        cleaned_workspace = str(workspace).strip()
        if not cleaned_workspace:
            self._publish(
                UiSnapshot(
                    False,
                    "Choose a project folder first.",
                    "warning",
                    None,
                    True,
                )
            )
            return False
        cleaned_task = str(task).strip()
        if not cleaned_task:
            self._publish(
                UiSnapshot(
                    False,
                    "Describe what you want ChatMPD to do.",
                    "warning",
                    None,
                    True,
                )
            )
            return False
        with self._lock:
            already_busy = self._busy
            if not already_busy:
                self._busy = True
        if already_busy:
            self._publish(
                UiSnapshot(
                    True,
                    "ChatMPD is already working on a task.",
                    "working",
                    None,
                    False,
                )
            )
            return False
        self._publish(
            UiSnapshot(
                True,
                "ChatMPD is working locally...",
                "working",
                None,
                False,
                cleaned_task,
            )
        )
        Thread(
            target=self._run,
            args=(Path(cleaned_workspace), cleaned_task),
            name="ChatMPD task",
            daemon=False,
        ).start()
        return True

    def _run(self, workspace: Path, task: str) -> None:
        try:
            outcome = self._task_runner(workspace, task)
            result = present_task_outcome(outcome)
        except Exception as error:
            result = present_error(error)
            self._schedule(lambda result=result: self._finish_error(result))
            return
        self._schedule(lambda result=result: self._finish_outcome(result))

    def _finish_outcome(self, result: TaskPresentation) -> None:
        with self._lock:
            self._busy = False
        succeeded = result.kind == "success"
        self._publish(
            UiSnapshot(
                False,
                (
                    "Task finished successfully."
                    if succeeded
                    else "Task finished, but its checks did not pass."
                ),
                "success" if succeeded else "warning",
                result,
                True,
            )
        )

    def _finish_error(self, result: TaskPresentation) -> None:
        with self._lock:
            self._busy = False
        self._publish(
            UiSnapshot(
                False,
                "ChatMPD could not finish this task.",
                "error",
                result,
                True,
            )
        )


def _load_toolkit() -> Any:
    """Load native Tk text widgets and themed ttk controls."""

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


class ChatMPDWindow:
    """A local-first assistant workspace backed by native Windows controls."""

    _COMPACT_BREAKPOINT = 900
    _TASK_PLACEHOLDER = (
        "Example: Repair the calculator, preserve its behavior, and run the tests."
    )

    def __init__(
        self,
        root: Any,
        task_runner: Callable[[Path, str], Any],
        *,
        toolkit: Any | None = None,
        choose_directory: Callable[[], str] | None = None,
        open_directory: Callable[[Path], None] | None = None,
        present_help: Callable[[str, str], None] | None = None,
    ) -> None:
        if toolkit is None:
            toolkit = _load_toolkit()
        if choose_directory is None:
            from tkinter import filedialog

            choose_directory = lambda: filedialog.askdirectory(
                parent=root,
                mustexist=True,
                title="Choose the project ChatMPD should work on",
            )
        if open_directory is None:
            open_directory = lambda directory: os.startfile(str(directory))
        if present_help is None:
            def present_help(title: str, message: str) -> None:
                from tkinter import messagebox

                messagebox.showinfo(parent=root, title=title, message=message)

        self._toolkit = toolkit
        self._choose_directory = choose_directory
        self._open_directory = open_directory
        self._present_help = present_help
        self._root = root
        self._workspace = toolkit.StringVar(value="")
        self._status = toolkit.StringVar(value="Ready for a local task.")
        self._project_state = toolkit.StringVar(value="Choose a project")
        self._theme = toolkit.StringVar(value="System")
        self._task_usage = toolkit.StringVar(value="0 / 32,768 bytes")
        self._submitted_task = ""
        self._current_result: TaskPresentation | None = None
        self._compact_layout: bool | None = None
        self._completion_focused = False
        self._placeholder_active = False
        self._help_open = False
        self._theme_name = "system"
        self._text_scale = 100
        try:
            self._base_scaling = float(root.tk.call("tk", "scaling"))
        except (AttributeError, TypeError, ValueError):
            self._base_scaling = 1.0
        self._style = toolkit.Style(root)
        self._native_theme = self._style.theme_use()

        root.title("ChatMPD — Local project assistant")
        root.geometry("1100x760")
        root.minsize(780, 640)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self._shell = toolkit.Frame(root, padding=(24, 20), style="App.TFrame")
        self._shell.grid(row=0, column=0, sticky="nsew")
        self._shell.columnconfigure(1, weight=1)
        self._shell.rowconfigure(1, weight=1)
        self._shell.rowconfigure(2, weight=1)

        self._build_header()
        self._build_project_panel()
        self._main_panel = toolkit.Frame(self._shell, style="App.TFrame")
        self._main_panel.columnconfigure(0, weight=1)
        self._main_panel.rowconfigure(1, weight=1)
        self._build_composer()
        self._build_timeline()
        self._build_footer()
        self._apply_theme("system", announce=False)

        self._controller = ChatMPDController(
            task_runner=task_runner,
            schedule=lambda callback: root.after(0, callback),
            publish=self._render,
        )
        self._bind_shortcuts()
        root.bind("<Configure>", self._on_configure)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._apply_layout(compact=False)
        self._render(
            UiSnapshot(
                False,
                "Ready for a local task.",
                "neutral",
                None,
                True,
            )
        )

    def _build_header(self) -> None:
        toolkit = self._toolkit
        header = toolkit.Frame(self._shell, style="App.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        header.columnconfigure(0, weight=1)
        toolkit.Label(
            header,
            text="ChatMPD",
            font=("Segoe UI", 22, "bold"),
            style="Header.TLabel",
        ).grid(row=0, column=0, sticky="w")
        toolkit.Label(
            header,
            text="A private workspace for real work in your local projects",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        toolkit.Label(
            header,
            text="Local · Private",
            style="Badge.TLabel",
        ).grid(row=0, column=1, sticky="e", padx=(12, 10))
        self._theme_selector = toolkit.Combobox(
            header,
            textvariable=self._theme,
            values=("System", "Light", "Dark"),
            state="readonly",
            width=9,
            takefocus=True,
            style="App.TCombobox",
        )
        self._theme_selector.grid(row=0, column=2, rowspan=2, sticky="e")
        self._theme_selector.bind("<<ComboboxSelected>>", self._on_theme_selected)
        self._help_button = toolkit.Button(
            header,
            text="Help",
            command=self._show_help,
            takefocus=True,
            style="App.TButton",
        )
        self._help_button.grid(
            row=0,
            column=3,
            rowspan=2,
            sticky="e",
            padx=(10, 0),
        )

    def _build_project_panel(self) -> None:
        toolkit = self._toolkit
        self._project_panel = toolkit.LabelFrame(
            self._shell,
            text="Project",
            padding=(16, 14),
            style="Card.TLabelframe",
        )
        self._project_panel.columnconfigure(0, weight=1)
        toolkit.Label(
            self._project_panel,
            text="Choose the folder ChatMPD may inspect and change.",
            wraplength=260,
            justify="left",
            style="Body.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self._choose_button = toolkit.Button(
            self._project_panel,
            text="Choose project",
            command=self._browse,
            takefocus=True,
            style="App.TButton",
        )
        self._workspace_entry = toolkit.Entry(
            self._project_panel,
            textvariable=self._workspace,
            state="readonly",
            takefocus=True,
            style="App.TEntry",
        )
        self._workspace_entry.grid(row=1, column=0, sticky="ew", pady=(12, 8))
        self._choose_button.grid(row=2, column=0, sticky="ew")
        toolkit.Separator(self._project_panel, style="App.TSeparator").grid(
            row=3, column=0, sticky="ew", pady=14
        )
        toolkit.Label(
            self._project_panel,
            textvariable=self._project_state,
            style="Body.TLabel",
        ).grid(row=4, column=0, sticky="w")
        toolkit.Label(
            self._project_panel,
            text="No cloud model or API key required.",
            wraplength=260,
            justify="left",
            style="CardMuted.TLabel",
        ).grid(row=5, column=0, sticky="w", pady=(6, 0))

    def _build_timeline(self) -> None:
        toolkit = self._toolkit
        toolkit.Label(
            self._main_panel,
            text="Task activity",
            font=("Segoe UI", 12, "bold"),
            style="Header.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        timeline_frame = toolkit.Frame(self._main_panel, style="Surface.TFrame")
        timeline_frame.grid(row=1, column=0, sticky="nsew")
        timeline_frame.columnconfigure(0, weight=1)
        timeline_frame.rowconfigure(0, weight=1)
        self._timeline = toolkit.Text(
            timeline_frame,
            wrap="word",
            state="disabled",
            padx=18,
            pady=16,
            borderwidth=1,
            relief="solid",
            takefocus=True,
        )
        self._timeline.grid(row=0, column=0, sticky="nsew")
        scrollbar = toolkit.Scrollbar(
            timeline_frame,
            orient="vertical",
            command=self._timeline.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._timeline.configure(yscrollcommand=scrollbar.set)
        self._timeline.tag_configure("heading", font=("Segoe UI", 9, "bold"))
        self._timeline.tag_configure("user", font=("Segoe UI", 11))
        self._timeline.tag_configure("assistant", font=("Segoe UI", 11))
        self._timeline.tag_configure("success", font=("Segoe UI", 10, "bold"))
        self._timeline.tag_configure("warning", font=("Segoe UI", 10, "bold"))
        self._timeline.tag_configure("error", font=("Segoe UI", 10, "bold"))
        self._timeline.tag_configure("muted", font=("Segoe UI", 9))
        self._result_box = self._timeline

        self._progress = toolkit.Progressbar(
            self._main_panel,
            mode="indeterminate",
            style="App.Horizontal.TProgressbar",
        )
        self._progress.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        actions = toolkit.Frame(self._main_panel, style="App.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self._copy_button = toolkit.Button(
            actions,
            text="Copy result",
            command=self._copy_result,
            state="disabled",
            takefocus=True,
            style="App.TButton",
        )
        self._copy_button.grid(row=0, column=0, sticky="w")
        self._open_button = toolkit.Button(
            actions,
            text="Open run folder",
            command=self._open_run_folder,
            state="disabled",
            takefocus=True,
            style="App.TButton",
        )
        self._open_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self._new_button = toolkit.Button(
            actions,
            text="New task",
            command=self._new_task,
            state="disabled",
            takefocus=True,
            style="App.TButton",
        )
        self._new_button.grid(row=0, column=2, sticky="w", padx=(8, 0))

    def _build_composer(self) -> None:
        toolkit = self._toolkit
        composer = toolkit.LabelFrame(
            self._main_panel,
            text="Describe the result you want",
            padding=(14, 12),
            style="Card.TLabelframe",
        )
        composer.grid(row=4, column=0, sticky="ew", pady=(14, 0))
        composer.columnconfigure(0, weight=1)
        self._task_box = toolkit.Text(
            composer,
            height=5,
            wrap="word",
            padx=10,
            pady=8,
            takefocus=True,
        )
        self._task_box.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._task_box.tag_configure("placeholder", font=("Segoe UI", 10, "italic"))
        self._task_box.bind("<FocusIn>", self._clear_placeholder)
        self._task_box.bind("<FocusOut>", self._restore_placeholder)
        self._task_box.bind("<KeyRelease>", self._update_task_usage)
        self._task_box.bind("<<Modified>>", self._update_task_usage)
        toolkit.Label(
            composer,
            text="Be specific about the outcome and the checks that must pass.",
            style="Body.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._start_button = toolkit.Button(
            composer,
            text="Start task",
            command=self._start,
            state="normal",
            takefocus=True,
            style="Accent.TButton",
        )
        self._start_button.grid(row=1, column=1, sticky="e", padx=(12, 0), pady=(8, 0))
        toolkit.Label(
            composer,
            textvariable=self._task_usage,
            style="CardMuted.TLabel",
        ).grid(
            row=2, column=0, sticky="w", pady=(6, 0)
        )
        self._set_placeholder()

    def _build_footer(self) -> None:
        toolkit = self._toolkit
        footer = toolkit.Frame(self._shell, style="App.TFrame")
        footer.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        footer.columnconfigure(0, weight=1)
        toolkit.Separator(footer, style="App.TSeparator").grid(
            row=0, column=0, columnspan=2, sticky="ew"
        )
        toolkit.Label(
            footer,
            textvariable=self._status,
            style="Header.TLabel",
        ).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        toolkit.Label(
            footer,
            text="Local execution · keep secrets out of tasks",
            style="Muted.TLabel",
        ).grid(
            row=1, column=1, sticky="e", pady=(8, 0)
        )

    def _browse(self) -> None:
        if hasattr(self, "_controller") and self._controller.busy:
            self._status.set("ChatMPD is working; the project cannot change yet.")
            return
        selected = self._choose_directory()
        if selected:
            self._workspace.set(selected)
            self._project_state.set("Project ready")
            self._status.set("Project selected. Describe the result you want.")
            self._clear_placeholder()
            self._task_box.focus_set()

    def _start(self) -> None:
        task = "" if self._placeholder_active else self._task_box.get("1.0", "end-1c")
        used, limit = task_byte_usage(task)
        if used > limit:
            self._status.set(
                f"Needs attention: the task is too long ({used:,} / {limit:,} bytes)."
            )
            self._task_box.focus_set()
            return
        self._controller.start(
            self._workspace.get(),
            task,
        )

    def _set_placeholder(self) -> None:
        if self._task_box.get("1.0", "end-1c").strip():
            return
        self._task_box.insert("1.0", self._TASK_PLACEHOLDER, "placeholder")
        self._placeholder_active = True
        self._update_task_usage()

    def _clear_placeholder(self, unused_event: Any = None) -> None:
        if self._placeholder_active:
            self._task_box.delete("1.0", "end")
            self._placeholder_active = False
            self._update_task_usage()

    def _restore_placeholder(self, unused_event: Any = None) -> None:
        if not self._task_box.get("1.0", "end-1c").strip():
            self._set_placeholder()

    def _update_task_usage(self, unused_event: Any = None) -> None:
        task = "" if self._placeholder_active else self._task_box.get("1.0", "end-1c")
        used, limit = task_byte_usage(task)
        suffix = " — too long" if used > limit else ""
        self._task_usage.set(f"{used:,} / {limit:,} bytes{suffix}")
        try:
            self._task_box.edit_modified(False)
        except (AttributeError, TypeError):
            pass

    def _bind_shortcuts(self) -> None:
        bindings = {
            "<Control-o>": lambda unused_event: self._shortcut_browse(),
            "<Control-l>": lambda unused_event: self._focus_composer(),
            "<Control-Return>": lambda unused_event: self._shortcut_start(),
            "<Control-Shift-C>": lambda unused_event: self._copy_result(),
            "<Control-n>": lambda unused_event: self._new_task(),
            "<Control-plus>": lambda unused_event: self._change_text_scale(1),
            "<Control-equal>": lambda unused_event: self._change_text_scale(1),
            "<Control-minus>": lambda unused_event: self._change_text_scale(-1),
            "<Control-0>": lambda unused_event: self._reset_text_scale(),
            "<F1>": lambda unused_event: self._show_help(),
            "<Escape>": lambda unused_event: self._escape(),
        }
        for sequence, callback in bindings.items():
            self._root.bind(sequence, callback)

    def _shortcut_browse(self) -> str:
        self._browse()
        return "break"

    def _focus_composer(self) -> str:
        self._clear_placeholder()
        self._task_box.focus_set()
        return "break"

    def _shortcut_start(self) -> str:
        self._start()
        return "break"

    def _copy_result(self) -> str:
        if self._current_result is None:
            self._set_action_error("No completed result is available to copy.")
            return "break"
        try:
            text = format_task_presentation(self._current_result)
            self._root.clipboard_clear()
            self._root.clipboard_append(text)
        except Exception as error:
            self._set_action_error(error)
            return "break"
        self._status.set("Result copied to the clipboard.")
        return "break"

    def _open_run_folder(self) -> str:
        if self._current_result is None or self._current_result.state_file is None:
            self._set_action_error("No saved run folder is available.")
            return "break"
        workspace_value = str(self._workspace.get()).strip()
        if not workspace_value:
            self._set_action_error("Choose the matching project before opening its run folder.")
            return "break"
        try:
            workspace = Path(workspace_value).resolve()
            state_file = Path(self._current_result.state_file).resolve()
            state_file.relative_to(workspace)
        except (OSError, ValueError) as error:
            self._set_action_error(
                "The saved run path is outside the selected project or cannot be resolved."
            )
            return "break"
        directory = state_file.parent
        if not directory.is_dir():
            self._set_action_error("The saved run folder no longer exists.")
            return "break"
        try:
            self._open_directory(directory)
        except Exception as error:
            self._set_action_error(error)
            return "break"
        self._status.set("Opened the saved run folder.")
        return "break"

    def _new_task(self) -> str:
        if self._controller.busy:
            self._set_action_error("Wait for the current task to finish safely.")
            return "break"
        self._submitted_task = ""
        self._current_result = None
        self._completion_focused = False
        self._clear_placeholder()
        self._task_box.configure(state="normal")
        self._task_box.delete("1.0", "end")
        self._update_task_usage()
        self._timeline.configure(state="normal")
        self._timeline.delete("1.0", "end")
        self._timeline.configure(state="disabled")
        self._copy_button.configure(state="disabled")
        self._open_button.configure(state="disabled")
        self._new_button.configure(state="disabled")
        self._status.set("Ready for a new local task.")
        self._task_box.focus_set()
        return "break"

    def _show_help(self) -> str:
        try:
            self._help_open = True
            self._present_help("ChatMPD Help", HELP_TEXT)
        except Exception as error:
            self._set_action_error(error)
        finally:
            self._help_open = False
        return "break"

    def _change_text_scale(self, direction: int) -> str:
        self._text_scale = step_text_scale(self._text_scale, direction)
        self._root.tk.call(
            "tk",
            "scaling",
            self._base_scaling * self._text_scale / 100,
        )
        self._status.set(f"Text size: {self._text_scale}%")
        return "break"

    def _reset_text_scale(self) -> str:
        self._text_scale = 100
        self._root.tk.call("tk", "scaling", self._base_scaling)
        self._status.set("Text size: 100%")
        return "break"

    def _escape(self) -> str:
        if self._help_open:
            self._help_open = False
            self._status.set("Help closed.")
            return "break"
        self._clear_placeholder()
        self._task_box.focus_set()
        return "break"

    def _set_action_error(self, detail: Any) -> None:
        normalized = " ".join(str(detail).split())[:300]
        if not normalized:
            normalized = "The desktop action could not be completed."
        self._status.set(f"Needs attention: {normalized}")

    def _on_theme_selected(self, unused_event: Any = None) -> str:
        self._apply_theme(self._theme.get())
        return "break"

    def _apply_theme(self, name: str, *, announce: bool = True) -> None:
        normalized = str(name).strip().casefold()
        if normalized not in {"system", "light", "dark"}:
            normalized = "system"
        self._theme_name = normalized
        self._theme.set(normalized.title())
        palette = palette_for(normalized)

        if normalized == "system":
            try:
                self._style.theme_use(self._native_theme)
            except Exception:
                pass
        else:
            try:
                self._style.theme_use("clam")
            except Exception:
                pass

        self._root.configure(background=palette.canvas)
        accent_background = (
            palette.elevated if normalized == "system" else palette.accent
        )
        accent_foreground = (
            palette.text if normalized == "system" else palette.accent_text
        )
        style_values = {
            "App.TFrame": {"background": palette.canvas},
            "Surface.TFrame": {"background": palette.surface},
            "Header.TLabel": {
                "background": palette.canvas,
                "foreground": palette.text,
            },
            "Body.TLabel": {
                "background": palette.surface,
                "foreground": palette.text,
            },
            "Muted.TLabel": {
                "background": palette.canvas,
                "foreground": palette.muted_text,
            },
            "CardMuted.TLabel": {
                "background": palette.surface,
                "foreground": palette.muted_text,
            },
            "Badge.TLabel": {
                "background": palette.elevated,
                "foreground": palette.success,
                "padding": (8, 4),
            },
            "Card.TLabelframe": {
                "background": palette.surface,
                "foreground": palette.text,
                "bordercolor": palette.border,
            },
            "Card.TLabelframe.Label": {
                "background": palette.surface,
                "foreground": palette.text,
            },
            "App.TButton": {
                "background": palette.elevated,
                "foreground": palette.text,
                "focuscolor": palette.focus,
            },
            "Accent.TButton": {
                "background": accent_background,
                "foreground": accent_foreground,
                "focuscolor": palette.focus,
            },
            "App.TEntry": {
                "fieldbackground": palette.elevated,
                "foreground": palette.text,
                "bordercolor": palette.border,
                "focuscolor": palette.focus,
            },
            "App.TCombobox": {
                "fieldbackground": palette.elevated,
                "foreground": palette.text,
                "bordercolor": palette.border,
                "focuscolor": palette.focus,
            },
            "App.Horizontal.TProgressbar": {
                "background": palette.accent,
                "troughcolor": palette.border,
            },
            "App.TSeparator": {"background": palette.border},
        }
        for style_name, values in style_values.items():
            self._style.configure(style_name, **values)
        self._style.map(
            "App.TButton",
            foreground=[("disabled", palette.muted_text)],
            background=[("active", palette.elevated)],
        )
        self._style.map(
            "Accent.TButton",
            foreground=[("disabled", palette.muted_text)],
            background=[("active", palette.focus)],
        )

        common_text = {
            "foreground": palette.text,
            "insertbackground": palette.text,
            "selectbackground": palette.accent,
            "selectforeground": palette.accent_text,
            "highlightbackground": palette.border,
            "highlightcolor": palette.focus,
        }
        self._task_box.configure(background=palette.elevated, **common_text)
        self._timeline.configure(background=palette.surface, **common_text)
        self._timeline.tag_configure("heading", foreground=palette.muted_text)
        self._timeline.tag_configure("user", foreground=palette.text)
        self._timeline.tag_configure("assistant", foreground=palette.text)
        self._timeline.tag_configure("success", foreground=palette.success)
        self._timeline.tag_configure("warning", foreground=palette.warning)
        self._timeline.tag_configure("error", foreground=palette.error)
        self._timeline.tag_configure("muted", foreground=palette.muted_text)
        self._task_box.tag_configure("placeholder", foreground=palette.muted_text)
        if announce:
            self._status.set(f"Appearance: {normalized.title()}")

    def _close(self) -> None:
        if self._controller.busy:
            self._status.set(
                "ChatMPD must finish safely before this window can close."
            )
            return
        self._root.destroy()

    def _on_configure(self, event: Any) -> None:
        if getattr(event, "widget", self._root) is not self._root:
            return
        width = int(getattr(event, "width", 1100))
        self._apply_layout(compact=width < self._COMPACT_BREAKPOINT)

    def _apply_layout(self, *, compact: bool) -> None:
        if compact == self._compact_layout:
            return
        self._compact_layout = compact
        if compact:
            self._project_panel.grid(
                row=1,
                column=0,
                columnspan=2,
                sticky="ew",
                pady=(0, 14),
            )
            self._main_panel.grid(
                row=2,
                column=0,
                columnspan=2,
                sticky="nsew",
            )
        else:
            self._project_panel.grid(
                row=1,
                column=0,
                columnspan=1,
                sticky="nsew",
                padx=(0, 18),
            )
            self._main_panel.grid(
                row=1,
                column=1,
                columnspan=1,
                sticky="nsew",
            )

    def _render(self, snapshot: UiSnapshot) -> None:
        self._status.set(snapshot.status)
        self._project_state.set(
            "Project ready" if str(self._workspace.get()).strip() else "Choose a project"
        )
        self._choose_button.configure(state="disabled" if snapshot.busy else "normal")
        self._workspace_entry.configure(
            state="disabled" if snapshot.busy else "readonly"
        )
        self._task_box.configure(state="disabled" if snapshot.busy else "normal")
        self._start_button.configure(
            state="normal" if snapshot.start_enabled else "disabled"
        )

        if snapshot.submitted_task:
            self._submitted_task = snapshot.submitted_task
            self._current_result = None
            self._completion_focused = False
        if snapshot.result is not None:
            self._current_result = snapshot.result

        if snapshot.tone == "working":
            self._progress.grid()
            self._progress.start(12)
        else:
            self._progress.stop()
            self._progress.grid_remove()

        self._render_timeline(snapshot)
        has_result = self._current_result is not None and not snapshot.busy
        self._copy_button.configure(state="normal" if has_result else "disabled")
        self._new_button.configure(state="normal" if has_result else "disabled")
        can_open = bool(
            has_result
            and self._current_result is not None
            and self._current_result.state_file is not None
        )
        self._open_button.configure(state="normal" if can_open else "disabled")

        if snapshot.status == "Choose a project folder first.":
            self._choose_button.focus_set()
        elif snapshot.status == "Describe what you want ChatMPD to do.":
            self._clear_placeholder()
            self._task_box.focus_set()
        elif (
            snapshot.result is not None
            and not snapshot.busy
            and not self._completion_focused
        ):
            self._timeline.focus_set()
            self._timeline.see("end")
            self._completion_focused = True

    def _render_timeline(self, snapshot: UiSnapshot) -> None:
        self._timeline.configure(state="normal")
        self._timeline.delete("1.0", "end")
        if self._submitted_task:
            self._timeline.insert("end", "YOU ASKED\n", "heading")
            self._timeline.insert("end", f"{self._submitted_task}\n\n", "user")

        if snapshot.busy:
            self._timeline.insert(
                "end", "CHATMPD IS WORKING LOCALLY\n", "heading"
            )
            self._timeline.insert(
                "end",
                "Your local model is working inside the selected project. "
                "ChatMPD will report the actual result when it finishes.\n",
                "assistant",
            )
        elif self._current_result is not None:
            result = self._current_result
            heading, tag = {
                "success": ("CHECKS PASSED", "success"),
                "verification_failed": ("CHECKS NEED ATTENTION", "warning"),
                "error": ("TASK COULD NOT FINISH", "error"),
            }[result.kind]
            self._timeline.insert("end", f"{heading}\n", tag)
            self._timeline.insert("end", f"{result.summary}\n\n", "assistant")

            self._timeline.insert("end", "CHANGED FILES\n", "heading")
            if result.changed_files:
                for path in result.changed_files:
                    self._timeline.insert("end", f"• {path}\n", "assistant")
            else:
                self._timeline.insert("end", "None\n", "muted")

            self._timeline.insert("end", "\nVERIFICATION\n", "heading")
            if result.checks:
                for check in result.checks:
                    label = "PASSED" if check.passed else "FAILED"
                    tag = "success" if check.passed else "error"
                    self._timeline.insert("end", f"{label} — {check.label}\n", tag)
            else:
                self._timeline.insert("end", "No checks recorded\n", "muted")

            if result.state_file is not None:
                self._timeline.insert("end", "\nRUN RECORD\n", "heading")
                self._timeline.insert("end", str(result.state_file), "muted")
        else:
            self._timeline.insert("end", "READY FOR A LOCAL TASK\n", "heading")
            self._timeline.insert(
                "end",
                "Choose a project and describe one concrete outcome. "
                "ChatMPD will show what changed and which checks passed.\n",
                "assistant",
            )
        self._timeline.configure(state="disabled")
        self._timeline.see("end")


def launch_gui(task_runner: Callable[[Path, str], Any]) -> None:
    """Open the ChatMPD desktop window and keep it running until closed."""

    import tkinter as tk

    root = tk.Tk()
    ChatMPDWindow(root, task_runner)
    root.mainloop()


def format_task_outcome(outcome: Any) -> str:
    """Turn a completed task outcome into a concise, nontechnical summary."""

    return format_task_presentation(present_task_outcome(outcome))
