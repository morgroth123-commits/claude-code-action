"""A small desktop interface for running ChatMPD project tasks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable

from chatmpd.presentation import (
    TaskPresentation,
    UiTone,
    format_task_presentation,
    present_error,
    present_task_outcome,
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


class ChatMPDWindow:
    """The nontechnical Tk desktop window, with dependencies supplied."""

    def __init__(
        self,
        root: Any,
        task_runner: Callable[[Path, str], Any],
        *,
        toolkit: Any | None = None,
        choose_directory: Callable[[], str] | None = None,
    ) -> None:
        if toolkit is None:
            import tkinter as toolkit
        if choose_directory is None:
            from tkinter import filedialog

            choose_directory = lambda: filedialog.askdirectory(
                parent=root,
                mustexist=True,
                title="Choose the project ChatMPD should work on",
            )

        self._choose_directory = choose_directory
        self._root = root
        self._workspace = toolkit.StringVar(value="")
        self._status = toolkit.StringVar(value="Ready.")

        root.title("ChatMPD")
        root.minsize(720, 640)
        content = toolkit.Frame(root, padx=24, pady=20)
        content.pack(fill="both", expand=True)

        toolkit.Label(
            content,
            text="ChatMPD",
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w")
        toolkit.Label(
            content,
            text="Choose a project, describe the result you want, then press Start.",
            justify="left",
        ).pack(anchor="w", pady=(4, 18))

        toolkit.Label(content, text="Project folder").pack(anchor="w")
        folder_row = toolkit.Frame(content)
        folder_row.pack(fill="x", pady=(4, 16))
        toolkit.Entry(
            folder_row,
            textvariable=self._workspace,
            state="readonly",
        ).pack(side="left", fill="x", expand=True)
        toolkit.Button(
            folder_row,
            text="Choose folder",
            command=self._browse,
        ).pack(side="left", padx=(8, 0))

        toolkit.Label(content, text="What should ChatMPD do?").pack(anchor="w")
        self._task_box = toolkit.Text(content, height=9, wrap="word")
        self._task_box.pack(fill="both", expand=False, pady=(4, 12))

        self._start_button = toolkit.Button(
            content,
            text="Start ChatMPD",
            command=self._start,
            state="normal",
        )
        self._start_button.pack(anchor="w", pady=(0, 14))

        toolkit.Label(content, textvariable=self._status).pack(anchor="w")
        toolkit.Label(content, text="Result").pack(anchor="w", pady=(16, 0))
        self._result_box = toolkit.Text(
            content,
            height=13,
            wrap="word",
            state="disabled",
        )
        self._result_box.pack(fill="both", expand=True, pady=(4, 0))

        self._controller = ChatMPDController(
            task_runner=task_runner,
            schedule=lambda callback: root.after(0, callback),
            publish=self._render,
        )
        root.protocol("WM_DELETE_WINDOW", self._close)

    def _browse(self) -> None:
        selected = self._choose_directory()
        if selected:
            self._workspace.set(selected)

    def _start(self) -> None:
        self._controller.start(
            self._workspace.get(),
            self._task_box.get("1.0", "end-1c"),
        )

    def _close(self) -> None:
        if self._controller.busy:
            self._status.set(
                "ChatMPD must finish safely before this window can close."
            )
            return
        self._root.destroy()

    def _render(self, snapshot: UiSnapshot) -> None:
        self._status.set(snapshot.status)
        self._start_button.configure(
            state="normal" if snapshot.start_enabled else "disabled"
        )
        self._result_box.configure(state="normal")
        self._result_box.delete("1.0", "end")
        if snapshot.result:
            self._result_box.insert(
                "1.0", format_task_presentation(snapshot.result)
            )
        self._result_box.configure(state="disabled")


def launch_gui(task_runner: Callable[[Path, str], Any]) -> None:
    """Open the ChatMPD desktop window and keep it running until closed."""

    import tkinter as tk

    root = tk.Tk()
    ChatMPDWindow(root, task_runner)
    root.mainloop()


def format_task_outcome(outcome: Any) -> str:
    """Turn a completed task outcome into a concise, nontechnical summary."""

    return format_task_presentation(present_task_outcome(outcome))
