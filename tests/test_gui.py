from __future__ import annotations

import sys
import unittest
from pathlib import Path
from queue import Queue
from threading import Event, get_ident
from types import SimpleNamespace
from unittest.mock import patch

from chatmpd.gui import (
    ChatMPDController,
    ChatMPDWindow,
    UiSnapshot,
    format_task_outcome,
    launch_gui,
)


def successful_outcome() -> SimpleNamespace:
    return SimpleNamespace(
        result=SimpleNamespace(
            status="succeeded",
            summary="Task complete.",
            changed_files=["calculator.py"],
            checks=[SimpleNamespace(argv=["python", "-m", "unittest"], exit_code=0)],
            state_file=Path("C:/project/.chatmpd/runs/1/run.json"),
        )
    )


class FakeVariable:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value


class FakeWidget:
    def __init__(self, kind: str, options: dict[str, object]) -> None:
        self.kind = kind
        self.options = dict(options)
        self.text = ""

    def pack(self, **unused: object) -> None:
        return None

    def configure(self, **options: object) -> None:
        self.options.update(options)

    def insert(self, unused_index: object, text: str) -> None:
        self.text = text

    def delete(self, unused_start: object, unused_end: object = None) -> None:
        self.text = ""

    def get(self, unused_start: object = None, unused_end: object = None) -> str:
        return self.text

    def invoke(self) -> None:
        command = self.options.get("command")
        if callable(command):
            command()


class FakeToolkit:
    def __init__(self) -> None:
        self.widgets: list[FakeWidget] = []
        self.root: FakeRoot | None = None
        self.filedialog = SimpleNamespace(askdirectory=lambda **unused: "")

    def Tk(self) -> "FakeRoot":
        self.root = FakeRoot()
        return self.root

    def StringVar(self, value: str = "") -> FakeVariable:
        return FakeVariable(value)

    def _widget(
        self, kind: str, unused_parent: object, **options: object
    ) -> FakeWidget:
        widget = FakeWidget(kind, options)
        self.widgets.append(widget)
        return widget

    def Frame(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Frame", parent, **options)

    def Label(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Label", parent, **options)

    def Entry(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Entry", parent, **options)

    def Button(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Button", parent, **options)

    def Text(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Text", parent, **options)

    def find(self, kind: str, text: str | None = None) -> FakeWidget:
        return next(
            widget
            for widget in self.widgets
            if widget.kind == kind
            and (text is None or widget.options.get("text") == text)
        )


class FakeRoot:
    def __init__(self) -> None:
        self.window_title = ""
        self.callbacks: Queue[object] = Queue()
        self.mainloop_calls = 0
        self.protocols: dict[str, object] = {}
        self.destroyed = False

    def title(self, value: str) -> None:
        self.window_title = value

    def minsize(self, unused_width: int, unused_height: int) -> None:
        return None

    def after(self, unused_delay: int, callback: object) -> None:
        self.callbacks.put(callback)

    def mainloop(self) -> None:
        self.mainloop_calls += 1

    def protocol(self, name: str, callback: object) -> None:
        self.protocols[name] = callback

    def destroy(self) -> None:
        self.destroyed = True


class TaskOutcomeFormattingTest(unittest.TestCase):
    def test_shows_summary_changed_files_checks_and_saved_state(self) -> None:
        outcome = SimpleNamespace(
            result=SimpleNamespace(
                status="succeeded",
                summary="Repaired the calculator.",
                changed_files=["calculator.py"],
                checks=[
                    SimpleNamespace(
                        argv=["python", "-m", "unittest"],
                        exit_code=0,
                    )
                ],
                state_file=Path("C:/project/.chatmpd/runs/1/run.json"),
            )
        )

        text = format_task_outcome(outcome)

        self.assertIn("Repaired the calculator.", text)
        self.assertIn("Changed files:\n- calculator.py", text)
        self.assertIn("Checks:\n- PASSED: python -m unittest", text)
        self.assertIn(
            f"Details saved at:\n{outcome.result.state_file}",
            text,
        )


class ChatMPDControllerTest(unittest.TestCase):
    def test_runs_task_in_background_and_publishes_success_on_ui_scheduler(
        self,
    ) -> None:
        release_runner = Event()
        runner_started = Event()
        runner_thread: list[int] = []
        scheduled: Queue[object] = Queue()
        snapshots: list[UiSnapshot] = []

        def runner(workspace: Path, task: str) -> SimpleNamespace:
            self.assertEqual(workspace, Path("C:/project"))
            self.assertEqual(task, "Repair the calculator")
            runner_thread.append(get_ident())
            runner_started.set()
            release_runner.wait(2)
            return successful_outcome()

        controller = ChatMPDController(
            task_runner=runner,
            schedule=scheduled.put,
            publish=snapshots.append,
        )

        accepted = controller.start("C:/project", "Repair the calculator")

        self.assertTrue(accepted)
        self.assertTrue(runner_started.wait(1))
        self.assertNotEqual(runner_thread, [get_ident()])
        self.assertTrue(controller.busy)
        self.assertEqual(snapshots[-1].status, "ChatMPD is working locally...")
        self.assertEqual(snapshots[-1].tone, "working")
        self.assertEqual(snapshots[-1].submitted_task, "Repair the calculator")
        self.assertIsNone(snapshots[-1].result)
        self.assertFalse(snapshots[-1].start_enabled)

        release_runner.set()
        scheduled.get(timeout=2)()

        self.assertFalse(controller.busy)
        self.assertEqual(snapshots[-1].status, "Task finished successfully.")
        self.assertEqual(snapshots[-1].tone, "success")
        self.assertEqual(snapshots[-1].result.kind, "success")
        self.assertEqual(snapshots[-1].result.changed_files, ("calculator.py",))
        self.assertTrue(snapshots[-1].start_enabled)

    def test_rejects_a_second_start_while_a_task_is_running(self) -> None:
        release_runner = Event()
        runner_started = Event()
        runner_calls = 0
        scheduled: Queue[object] = Queue()
        snapshots: list[UiSnapshot] = []

        def runner(unused_workspace: Path, unused_task: str) -> SimpleNamespace:
            nonlocal runner_calls
            runner_calls += 1
            runner_started.set()
            release_runner.wait(2)
            return successful_outcome()

        controller = ChatMPDController(
            task_runner=runner,
            schedule=scheduled.put,
            publish=snapshots.append,
        )
        self.assertTrue(controller.start("C:/project", "First task"))
        self.assertTrue(runner_started.wait(1))

        accepted = controller.start("C:/other", "Second task")

        self.assertFalse(accepted)
        self.assertEqual(runner_calls, 1)
        self.assertTrue(controller.busy)
        self.assertEqual(
            snapshots[-1].status,
            "ChatMPD is already working on a task.",
        )
        self.assertEqual(snapshots[-1].tone, "working")
        self.assertIsNone(snapshots[-1].result)
        self.assertFalse(snapshots[-1].start_enabled)

        release_runner.set()
        scheduled.get(timeout=2)()

    def test_rejects_a_missing_workspace_before_starting_a_worker(self) -> None:
        snapshots: list[UiSnapshot] = []

        def runner(unused_workspace: Path, unused_task: str) -> SimpleNamespace:
            self.fail("The task runner must not be called without a workspace")

        controller = ChatMPDController(
            task_runner=runner,
            schedule=lambda callback: callback(),
            publish=snapshots.append,
        )

        accepted = controller.start("   ", "Repair the calculator")

        self.assertFalse(accepted)
        self.assertFalse(controller.busy)
        self.assertEqual(snapshots[-1].status, "Choose a project folder first.")
        self.assertEqual(snapshots[-1].tone, "warning")
        self.assertIsNone(snapshots[-1].result)
        self.assertTrue(snapshots[-1].start_enabled)

    def test_rejects_a_blank_task_before_starting_a_worker(self) -> None:
        snapshots: list[UiSnapshot] = []

        def runner(unused_workspace: Path, unused_task: str) -> SimpleNamespace:
            self.fail("The task runner must not be called without a task")

        controller = ChatMPDController(
            task_runner=runner,
            schedule=lambda callback: callback(),
            publish=snapshots.append,
        )

        accepted = controller.start("C:/project", " \n\t ")

        self.assertFalse(accepted)
        self.assertFalse(controller.busy)
        self.assertEqual(snapshots[-1].status, "Describe what you want ChatMPD to do.")
        self.assertEqual(snapshots[-1].tone, "warning")
        self.assertIsNone(snapshots[-1].result)
        self.assertTrue(snapshots[-1].start_enabled)

    def test_turns_worker_failure_into_a_friendly_retryable_result(self) -> None:
        scheduled: Queue[object] = Queue()
        snapshots: list[UiSnapshot] = []

        def runner(unused_workspace: Path, unused_task: str) -> SimpleNamespace:
            raise RuntimeError("The local ChatMPD model is not ready")

        controller = ChatMPDController(
            task_runner=runner,
            schedule=scheduled.put,
            publish=snapshots.append,
        )

        self.assertTrue(controller.start("C:/project", "Repair the calculator"))
        scheduled.get(timeout=2)()

        self.assertFalse(controller.busy)
        self.assertEqual(
            snapshots[-1].status,
            "ChatMPD could not finish this task.",
        )
        self.assertEqual(snapshots[-1].tone, "error")
        self.assertEqual(snapshots[-1].result.kind, "error")
        self.assertEqual(
            snapshots[-1].result.summary,
            "The local ChatMPD model is not ready",
        )
        self.assertTrue(snapshots[-1].start_enabled)

    def test_reports_a_completed_outcome_whose_verification_failed(self) -> None:
        scheduled: Queue[object] = Queue()
        snapshots: list[UiSnapshot] = []
        outcome = successful_outcome()
        outcome.result.status = "failed"
        outcome.result.summary = "The requested repair did not pass its checks."
        outcome.result.checks[0].exit_code = 1

        controller = ChatMPDController(
            task_runner=lambda unused_workspace, unused_task: outcome,
            schedule=scheduled.put,
            publish=snapshots.append,
        )

        self.assertTrue(controller.start("C:/project", "Repair the calculator"))
        scheduled.get(timeout=2)()

        self.assertFalse(controller.busy)
        self.assertEqual(
            snapshots[-1].status,
            "Task finished, but its checks did not pass.",
        )
        self.assertEqual(snapshots[-1].tone, "warning")
        self.assertEqual(snapshots[-1].result.kind, "verification_failed")
        self.assertFalse(snapshots[-1].result.checks[0].passed)
        self.assertTrue(snapshots[-1].start_enabled)


class ChatMPDWindowTest(unittest.TestCase):
    def test_window_closes_when_idle_but_waits_for_runtime_cleanup_when_busy(self) -> None:
        toolkit = FakeToolkit()
        root = FakeRoot()
        release_runner = Event()
        runner_started = Event()

        def runner(unused_workspace: Path, unused_task: str) -> SimpleNamespace:
            runner_started.set()
            release_runner.wait(2)
            return successful_outcome()

        window = ChatMPDWindow(
            root,
            runner,
            toolkit=toolkit,
            choose_directory=lambda: "C:/project",
        )
        window._workspace.set("C:/project")
        window._task_box.insert("1.0", "Repair the calculator")
        window._start()
        self.assertTrue(runner_started.wait(1))

        close = root.protocols["WM_DELETE_WINDOW"]
        self.assertTrue(callable(close))
        close()

        self.assertFalse(root.destroyed)
        self.assertIn("finish safely", window._status.get())

        release_runner.set()
        root.callbacks.get(timeout=2)()
        close()
        self.assertTrue(root.destroyed)

    def test_folder_task_and_start_controls_render_the_finished_result(self) -> None:
        toolkit = FakeToolkit()
        root = FakeRoot()
        runner_started = Event()

        def runner(workspace: Path, task: str) -> SimpleNamespace:
            self.assertEqual(workspace, Path("C:/project"))
            self.assertEqual(task, "Repair the calculator")
            runner_started.set()
            return successful_outcome()

        ChatMPDWindow(
            root,
            runner,
            toolkit=toolkit,
            choose_directory=lambda: "C:/project",
        )

        self.assertEqual(root.window_title, "ChatMPD")
        toolkit.find("Button", "Choose folder").invoke()
        workspace_entry = toolkit.find("Entry")
        self.assertEqual(workspace_entry.options["textvariable"].get(), "C:/project")

        task_box, result_box = [
            widget for widget in toolkit.widgets if widget.kind == "Text"
        ]
        task_box.insert("1.0", "Repair the calculator")
        start_button = toolkit.find("Button", "Start ChatMPD")
        start_button.invoke()

        self.assertTrue(runner_started.wait(1))
        root.callbacks.get(timeout=2)()

        status_variable = next(
            widget.options["textvariable"]
            for widget in toolkit.widgets
            if widget.kind == "Label" and "textvariable" in widget.options
        )
        self.assertEqual(status_variable.get(), "Task finished successfully.")
        self.assertIn("Changed files:\n- calculator.py", result_box.text)
        self.assertEqual(start_button.options["state"], "normal")

    def test_launch_gui_builds_the_window_and_enters_the_desktop_event_loop(
        self,
    ) -> None:
        toolkit = FakeToolkit()

        with patch.dict(sys.modules, {"tkinter": toolkit}):
            launch_gui(lambda unused_workspace, unused_task: successful_outcome())

        self.assertIsNotNone(toolkit.root)
        self.assertEqual(toolkit.root.mainloop_calls, 1)
        self.assertEqual(toolkit.root.window_title, "ChatMPD")
        toolkit.find("Button", "Start ChatMPD")


if __name__ == "__main__":
    unittest.main()
