from __future__ import annotations

import sys
import unittest
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
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
from chatmpd.presentation import (
    HELP_TEXT,
    format_task_presentation,
    palette_for,
    present_task_outcome,
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
    def __init__(
        self,
        kind: str,
        options: dict[str, object],
        toolkit: "FakeToolkit",
    ) -> None:
        self.kind = kind
        self.options = dict(options)
        self.toolkit = toolkit
        self.text = ""
        self.grid_calls: list[dict[str, object]] = []
        self.grid_configure_calls: list[dict[str, object]] = []
        self.pack_calls: list[dict[str, object]] = []
        self.bindings: dict[str, object] = {}
        self.tags: dict[str, dict[str, object]] = {}
        self.see_calls: list[object] = []
        self.focus_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.visible = True
        self.columns: dict[int, int] = {}
        self.rows: dict[int, int] = {}

    def pack(self, **options: object) -> None:
        self.pack_calls.append(dict(options))
        self.visible = True

    def pack_forget(self) -> None:
        self.visible = False

    def grid(self, **options: object) -> None:
        self.grid_calls.append(dict(options))
        self.visible = True

    def grid_configure(self, **options: object) -> None:
        self.grid_configure_calls.append(dict(options))
        if self.grid_calls:
            self.grid_calls[-1].update(options)

    def grid_remove(self) -> None:
        self.visible = False

    def columnconfigure(self, column: int, weight: int = 0, **unused: object) -> None:
        self.columns[column] = weight

    def rowconfigure(self, row: int, weight: int = 0, **unused: object) -> None:
        self.rows[row] = weight

    def configure(self, **options: object) -> None:
        self.options.update(options)

    config = configure

    def insert(
        self,
        unused_index: object,
        text: str,
        unused_tags: object = None,
    ) -> None:
        self.text += text

    def delete(self, unused_start: object, unused_end: object = None) -> None:
        self.text = ""

    def get(self, unused_start: object = None, unused_end: object = None) -> str:
        return self.text

    def invoke(self) -> None:
        command = self.options.get("command")
        if callable(command):
            command()

    def bind(self, sequence: str, callback: object) -> None:
        self.bindings[sequence] = callback

    def focus_set(self) -> None:
        self.focus_calls += 1
        self.toolkit.focused_widget = self
        if self.toolkit.root is not None:
            self.toolkit.root.focused_widget = self

    def tag_configure(self, name: str, **options: object) -> None:
        self.tags[name] = dict(options)

    tag_config = tag_configure

    def see(self, index: object) -> None:
        self.see_calls.append(index)

    def start(self, unused_interval: int = 50) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    def yview(self, *unused: object) -> None:
        return None

    def set(self, *unused: object) -> None:
        return None


class FakeStyle:
    def __init__(self) -> None:
        self.configurations: dict[str, dict[str, object]] = {}
        self.maps: dict[str, dict[str, object]] = {}
        self.theme = "system"

    def configure(self, name: str, **options: object) -> None:
        self.configurations.setdefault(name, {}).update(options)

    def map(self, name: str, **options: object) -> None:
        self.maps.setdefault(name, {}).update(options)

    def theme_use(self, name: str | None = None) -> str:
        if name is not None:
            self.theme = name
        return self.theme


class FakeTk:
    def __init__(self) -> None:
        self.scaling = 1.3333333333

    def call(self, *args: object) -> float:
        if args[:2] != ("tk", "scaling"):
            return self.scaling
        if len(args) == 3:
            self.scaling = float(args[2])
        return self.scaling


class FakeToolkit:
    def __init__(self) -> None:
        self.widgets: list[FakeWidget] = []
        self.root: FakeRoot | None = None
        self.focused_widget: FakeWidget | None = None
        self.style = FakeStyle()
        self.filedialog = SimpleNamespace(askdirectory=lambda **unused: "")
        self.ttk = self

    def Tk(self) -> "FakeRoot":
        self.root = FakeRoot()
        return self.root

    def StringVar(self, value: str = "") -> FakeVariable:
        return FakeVariable(value)

    def _widget(
        self, kind: str, parent: object, **options: object
    ) -> FakeWidget:
        if isinstance(parent, FakeRoot):
            self.root = parent
        widget = FakeWidget(kind, options, self)
        self.widgets.append(widget)
        return widget

    def Frame(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Frame", parent, **options)

    def Label(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Label", parent, **options)

    def LabelFrame(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("LabelFrame", parent, **options)

    def Entry(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Entry", parent, **options)

    def Button(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Button", parent, **options)

    def Text(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Text", parent, **options)

    def Scrollbar(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Scrollbar", parent, **options)

    def Progressbar(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Progressbar", parent, **options)

    def Combobox(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Combobox", parent, **options)

    def Separator(self, parent: object, **options: object) -> FakeWidget:
        return self._widget("Separator", parent, **options)

    def Style(self, unused_root: object = None) -> FakeStyle:
        return self.style

    def find(self, kind: str, text: str | None = None) -> FakeWidget:
        return next(
            widget
            for widget in self.widgets
            if widget.kind == kind
            and (text is None or widget.options.get("text") == text)
        )

    def label_texts(self) -> list[str]:
        return [
            str(widget.options.get("text", ""))
            for widget in self.widgets
            if widget.kind in {"Label", "LabelFrame"}
        ]


class FakeRoot:
    def __init__(self) -> None:
        self.window_title = ""
        self.window_geometry = ""
        self.options: dict[str, object] = {}
        self.callbacks: Queue[object] = Queue()
        self.mainloop_calls = 0
        self.protocols: dict[str, object] = {}
        self.bindings: dict[str, object] = {}
        self.columns: dict[int, int] = {}
        self.rows: dict[int, int] = {}
        self.clipboard = ""
        self.focused_widget: FakeWidget | None = None
        self.tk = FakeTk()
        self.destroyed = False

    def title(self, value: str) -> None:
        self.window_title = value

    def minsize(self, unused_width: int, unused_height: int) -> None:
        return None

    def geometry(self, value: str) -> None:
        self.window_geometry = value

    def configure(self, **options: object) -> None:
        self.options.update(options)

    config = configure

    def bind(self, sequence: str, callback: object) -> None:
        self.bindings[sequence] = callback

    def columnconfigure(self, column: int, weight: int = 0, **unused: object) -> None:
        self.columns[column] = weight

    def rowconfigure(self, row: int, weight: int = 0, **unused: object) -> None:
        self.rows[row] = weight

    def clipboard_clear(self) -> None:
        self.clipboard = ""

    def clipboard_append(self, text: str) -> None:
        self.clipboard += text

    def focus_get(self) -> FakeWidget | None:
        return self.focused_widget

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


class ChatMPDWindowConstructionTest(unittest.TestCase):
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
        window._clear_placeholder()
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

    def test_builds_local_private_assistant_workspace_and_selects_project(self) -> None:
        toolkit = FakeToolkit()
        root = FakeRoot()
        window = ChatMPDWindow(
            root,
            lambda unused_workspace, unused_task: successful_outcome(),
            toolkit=toolkit,
            choose_directory=lambda: "C:/project",
        )

        self.assertEqual(root.window_title, "ChatMPD — Local project assistant")
        self.assertEqual(root.window_geometry, "1100x760")
        toolkit.find("Label", "Local · Private")
        toolkit.find("Button", "Choose project")
        toolkit.find("Button", "Start task")
        toolkit.find("Button", "Help")
        self.assertTrue(
            any("Describe the result you want" in text for text in toolkit.label_texts())
        )
        self.assertTrue(any("No cloud model" in text for text in toolkit.label_texts()))
        self.assertFalse(window._progress.visible)

        toolkit.find("Button", "Choose project").invoke()
        workspace_entry = toolkit.find("Entry")
        self.assertEqual(workspace_entry.options["textvariable"].get(), "C:/project")
        self.assertEqual(window._workspace.get(), "C:/project")


class ChatMPDWindowAccessibilityTest(unittest.TestCase):
    def test_binds_documented_shortcuts_and_routes_composer_focus(self) -> None:
        toolkit = FakeToolkit()
        root = FakeRoot()
        window = ChatMPDWindow(
            root,
            lambda unused_workspace, unused_task: successful_outcome(),
            toolkit=toolkit,
            choose_directory=lambda: "C:/project",
        )

        expected = {
            "<Control-o>",
            "<Control-l>",
            "<Control-Return>",
            "<Control-Shift-C>",
            "<Control-n>",
            "<Control-plus>",
            "<Control-equal>",
            "<Control-minus>",
            "<Control-0>",
            "<F1>",
            "<Escape>",
        }
        self.assertTrue(expected.issubset(root.bindings))
        self.assertNotIn("<Return>", root.bindings)

        self.assertEqual(root.bindings["<Control-l>"](SimpleNamespace()), "break")
        self.assertIs(root.focus_get(), window._task_box)

        starts: list[bool] = []
        window._start = lambda: starts.append(True)
        self.assertEqual(
            root.bindings["<Control-Return>"](SimpleNamespace()),
            "break",
        )
        self.assertEqual(starts, [True])

    def test_native_focus_order_matches_the_visual_workflow(self) -> None:
        toolkit = FakeToolkit()
        root = FakeRoot()
        window = ChatMPDWindow(
            root,
            lambda unused_workspace, unused_task: successful_outcome(),
            toolkit=toolkit,
            choose_directory=lambda: "C:/project",
        )

        focusable = [
            widget for widget in toolkit.widgets if widget.options.get("takefocus") is True
        ]
        self.assertEqual(
            focusable,
            [
                window._theme_selector,
                window._help_button,
                window._choose_button,
                window._workspace_entry,
                window._task_box,
                window._start_button,
                window._timeline,
                window._copy_button,
                window._open_button,
                window._new_button,
            ],
        )

    def test_validation_and_completion_focus_only_when_actionable(self) -> None:
        toolkit = FakeToolkit()
        root = FakeRoot()
        scheduled: Queue[object] = Queue()
        window = ChatMPDWindow(
            root,
            lambda unused_workspace, unused_task: successful_outcome(),
            toolkit=toolkit,
            choose_directory=lambda: "C:/project",
        )
        window._controller._schedule = scheduled.put

        self.assertFalse(window._controller.start("", "Repair the calculator"))
        self.assertIs(root.focus_get(), window._choose_button)

        self.assertFalse(window._controller.start("C:/project", " \n "))
        self.assertIs(root.focus_get(), window._task_box)

        self.assertTrue(window._controller.start("C:/project", "Repair the calculator"))
        scheduled.get(timeout=2)()
        self.assertIs(root.focus_get(), window._timeline)
        self.assertEqual(window._timeline.focus_calls, 1)

        window._render(
            UiSnapshot(
                False,
                "Task finished successfully.",
                "success",
                window._current_result,
                True,
            )
        )
        self.assertEqual(window._timeline.focus_calls, 1)

        window._status.set("A background note changed.")
        self.assertEqual(window._timeline.focus_calls, 1)


class ChatMPDWindowTest(unittest.TestCase):
    def test_renders_honest_working_and_structured_completed_timeline(self) -> None:
        toolkit = FakeToolkit()
        root = FakeRoot()
        release_runner = Event()
        runner_started = Event()

        def runner(workspace: Path, task: str) -> SimpleNamespace:
            self.assertEqual(workspace, Path("C:/project"))
            self.assertEqual(task, "Repair the calculator")
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
        window._clear_placeholder()
        window._task_box.insert("1.0", "Repair the calculator")
        start_button = toolkit.find("Button", "Start task")
        start_button.invoke()

        self.assertTrue(runner_started.wait(1))
        self.assertIn("YOU ASKED", window._timeline.text)
        self.assertIn("Repair the calculator", window._timeline.text)
        self.assertIn("CHATMPD IS WORKING LOCALLY", window._timeline.text)
        self.assertGreaterEqual(window._progress.start_calls, 1)
        self.assertTrue(window._progress.visible)
        self.assertEqual(start_button.options["state"], "disabled")

        release_runner.set()
        root.callbacks.get(timeout=2)()

        self.assertIn("CHECKS PASSED", window._timeline.text)
        self.assertIn("CHANGED FILES", window._timeline.text)
        self.assertIn("calculator.py", window._timeline.text)
        self.assertIn("VERIFICATION", window._timeline.text)
        self.assertIn(
            "C:\\project\\.chatmpd\\runs\\1\\run.json".casefold(),
            window._timeline.text.casefold(),
        )
        self.assertGreaterEqual(window._progress.stop_calls, 1)
        self.assertFalse(window._progress.visible)
        self.assertEqual(toolkit.find("Button", "Copy result").options["state"], "normal")
        self.assertEqual(
            toolkit.find("Button", "Open run folder").options["state"], "normal"
        )
        self.assertEqual(toolkit.find("Button", "New task").options["state"], "normal")
        self.assertEqual(start_button.options["state"], "normal")

    def test_launch_gui_builds_the_window_and_enters_the_desktop_event_loop(
        self,
    ) -> None:
        toolkit = FakeToolkit()

        with patch.dict(sys.modules, {"tkinter": toolkit}):
            launch_gui(lambda unused_workspace, unused_task: successful_outcome())

        self.assertIsNotNone(toolkit.root)
        self.assertEqual(toolkit.root.mainloop_calls, 1)
        self.assertEqual(
            toolkit.root.window_title,
            "ChatMPD — Local project assistant",
        )
        toolkit.find("Button", "Start task")


class ChatMPDWindowAppearanceTest(unittest.TestCase):
    def test_supports_system_light_and_dark_with_palette_owned_text_colors(self) -> None:
        toolkit = FakeToolkit()
        root = FakeRoot()
        window = ChatMPDWindow(
            root,
            lambda unused_workspace, unused_task: successful_outcome(),
            toolkit=toolkit,
            choose_directory=lambda: "C:/project",
        )

        selector = toolkit.find("Combobox")
        self.assertEqual(selector.options["values"], ("System", "Light", "Dark"))
        for name in ("system", "light", "dark"):
            window._apply_theme(name)
            self.assertEqual(window._theme_name, name)
            palette = palette_for(name)
            colors = {
                palette.canvas,
                palette.surface,
                palette.elevated,
                palette.border,
                palette.text,
                palette.muted_text,
                palette.accent,
                palette.accent_text,
                palette.focus,
                palette.success,
                palette.warning,
                palette.error,
            }
            for widget in (window._task_box, window._timeline):
                self.assertIn(widget.options["background"], colors)
                self.assertIn(widget.options["foreground"], colors)
                self.assertIn(widget.options["insertbackground"], colors)
                self.assertIn(widget.options["selectbackground"], colors)
                self.assertIn(widget.options["selectforeground"], colors)

        window._apply_theme("not-a-theme")
        self.assertEqual(window._theme_name, "system")
        self.assertEqual(window._theme.get(), "System")
        self.assertEqual(
            toolkit.style.configurations["Accent.TButton"]["foreground"],
            palette_for("system").text,
        )

    def test_text_scaling_uses_bounded_steps_and_reset(self) -> None:
        toolkit = FakeToolkit()
        root = FakeRoot()
        base_scaling = root.tk.scaling
        window = ChatMPDWindow(
            root,
            lambda unused_workspace, unused_task: successful_outcome(),
            toolkit=toolkit,
            choose_directory=lambda: "C:/project",
        )

        self.assertEqual(window._text_scale, 100)
        self.assertEqual(root.bindings["<Control-plus>"](SimpleNamespace()), "break")
        self.assertEqual(window._text_scale, 110)
        self.assertAlmostEqual(root.tk.scaling, base_scaling * 1.1)
        for unused in range(10):
            root.bindings["<Control-plus>"](SimpleNamespace())
        self.assertEqual(window._text_scale, 160)
        for unused in range(10):
            root.bindings["<Control-minus>"](SimpleNamespace())
        self.assertEqual(window._text_scale, 90)
        self.assertEqual(root.bindings["<Control-0>"](SimpleNamespace()), "break")
        self.assertEqual(window._text_scale, 100)
        self.assertAlmostEqual(root.tk.scaling, base_scaling)


class ChatMPDWindowActionTest(unittest.TestCase):
    def test_copy_open_help_and_new_task_are_real_safe_actions(self) -> None:
        with TemporaryDirectory() as temporary:
            project = Path(temporary)
            run_folder = project / ".chatmpd" / "runs" / "1"
            run_folder.mkdir(parents=True)
            outcome = successful_outcome()
            outcome.result.state_file = run_folder / "run.json"
            result = present_task_outcome(outcome)
            opened: list[Path] = []
            help_calls: list[tuple[str, str]] = []
            toolkit = FakeToolkit()
            root = FakeRoot()
            window = ChatMPDWindow(
                root,
                lambda unused_workspace, unused_task: outcome,
                toolkit=toolkit,
                choose_directory=lambda: str(project),
                open_directory=opened.append,
                present_help=lambda title, message: help_calls.append((title, message)),
            )
            window._workspace.set(str(project))
            window._submitted_task = "Repair the calculator"
            window._render(
                UiSnapshot(
                    False,
                    "Task finished successfully.",
                    "success",
                    result,
                    True,
                )
            )

            toolkit.find("Button", "Copy result").invoke()
            self.assertEqual(root.clipboard, format_task_presentation(result))
            toolkit.find("Button", "Open run folder").invoke()
            self.assertEqual(opened, [run_folder.resolve()])
            toolkit.find("Button", "Help").invoke()
            self.assertEqual(help_calls, [("ChatMPD Help", HELP_TEXT)])

            window._task_box.delete("1.0", "end")
            window._task_box.insert("1.0", "A follow-up task")
            toolkit.find("Button", "New task").invoke()
            self.assertEqual(window._workspace.get(), str(project))
            self.assertEqual(window._task_box.get("1.0", "end-1c"), "")
            self.assertEqual(window._timeline.text, "")
            self.assertIs(root.focus_get(), window._task_box)

    def test_rejects_unsafe_or_missing_run_paths_without_opening(self) -> None:
        with TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            opened: list[Path] = []
            toolkit = FakeToolkit()
            root = FakeRoot()
            window = ChatMPDWindow(
                root,
                lambda unused_workspace, unused_task: successful_outcome(),
                toolkit=toolkit,
                choose_directory=lambda: str(project),
                open_directory=opened.append,
            )
            window._workspace.set(str(project))
            outcome = successful_outcome()
            outcome.result.state_file = project.parent / "outside" / "run.json"
            window._current_result = present_task_outcome(outcome)

            self.assertEqual(window._open_run_folder(), "break")
            self.assertEqual(opened, [])
            self.assertTrue(window._status.get().startswith("Needs attention:"))
            self.assertLessEqual(len(window._status.get()), 340)

            window._current_result = None
            self.assertEqual(window._open_run_folder(), "break")
            self.assertEqual(opened, [])
            self.assertTrue(window._status.get().startswith("Needs attention:"))

    def test_desktop_action_errors_are_nonfatal_and_bounded(self) -> None:
        with TemporaryDirectory() as temporary:
            project = Path(temporary)
            run_folder = project / ".chatmpd" / "runs" / "1"
            run_folder.mkdir(parents=True)
            outcome = successful_outcome()
            outcome.result.state_file = run_folder / "run.json"
            toolkit = FakeToolkit()
            root = FakeRoot()

            def fail_open(unused_path: Path) -> None:
                raise OSError("desktop opener failed\n" + "x" * 1_000)

            window = ChatMPDWindow(
                root,
                lambda unused_workspace, unused_task: outcome,
                toolkit=toolkit,
                choose_directory=lambda: str(project),
                open_directory=fail_open,
            )
            window._workspace.set(str(project))
            window._current_result = present_task_outcome(outcome)

            def fail_clipboard(unused_text: str) -> None:
                raise RuntimeError("clipboard unavailable")

            root.clipboard_append = fail_clipboard
            self.assertEqual(window._copy_result(), "break")
            self.assertTrue(window._status.get().startswith("Needs attention:"))
            self.assertEqual(window._open_run_folder(), "break")
            self.assertTrue(window._status.get().startswith("Needs attention:"))
            self.assertLessEqual(len(window._status.get()), 340)

    def test_placeholder_is_never_submitted_and_counter_uses_utf8_bytes(self) -> None:
        calls: list[str] = []
        toolkit = FakeToolkit()
        root = FakeRoot()
        window = ChatMPDWindow(
            root,
            lambda unused_workspace, task: calls.append(task) or successful_outcome(),
            toolkit=toolkit,
            choose_directory=lambda: "C:/project",
        )
        window._workspace.set("C:/project")

        self.assertTrue(window._placeholder_active)
        window._start()
        self.assertEqual(calls, [])
        self.assertIs(root.focus_get(), window._task_box)

        window._clear_placeholder()
        window._task_box.insert("1.0", "Aé")
        window._update_task_usage()
        self.assertEqual(window._task_usage.get(), "3 / 32,768 bytes")

        window._task_box.delete("1.0", "end")
        window._task_box.insert("1.0", "x" * 32_769)
        window._update_task_usage()
        window._start()
        self.assertEqual(calls, [])
        self.assertIn("too long", window._status.get().lower())
        self.assertIs(root.focus_get(), window._task_box)


if __name__ == "__main__":
    unittest.main()
