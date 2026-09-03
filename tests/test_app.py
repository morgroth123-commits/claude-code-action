from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace


class _FakeRuntime:
    endpoint = "http://127.0.0.1:9090"

    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    def __enter__(self) -> "_FakeRuntime":
        self.entered = True
        return self

    def __exit__(self, *_exc: object) -> None:
        self.exited = True


class ApplicationDispatchTest(unittest.TestCase):
    def test_no_arguments_launches_the_desktop_ui_with_the_local_task_runner(self) -> None:
        from chatmpd.app import dispatch

        launched: list[object] = []

        result = dispatch(
            [],
            cli_runner=lambda unused: self.fail("CLI must not run on double-click"),
            gui_launcher=launched.append,
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(launched), 1)
        self.assertTrue(callable(launched[0]))

    def test_arguments_are_forwarded_to_the_cli_without_opening_a_window(self) -> None:
        from chatmpd.app import dispatch

        received: list[list[str]] = []

        result = dispatch(
            ["doctor"],
            cli_runner=lambda arguments: received.append(arguments) or 3,
            gui_launcher=lambda unused: self.fail("GUI must not open for CLI commands"),
        )

        self.assertEqual(result, 3)
        self.assertEqual(received, [["doctor"]])

    def test_local_task_runner_starts_and_always_stops_its_owned_runtime(self) -> None:
        from chatmpd.app import run_local_task

        runtime = _FakeRuntime()
        calls: list[tuple[Path, str, str]] = []
        expected = SimpleNamespace(result=SimpleNamespace(status="succeeded"))
        expected_prepared = object()
        preflight_finished = False

        def preflight(workspace: Path, task: str) -> object:
            nonlocal preflight_finished
            self.assertEqual((workspace, task), (Path("C:/project"), "Repair it"))
            preflight_finished = True
            return expected_prepared

        def runtime_factory() -> _FakeRuntime:
            self.assertTrue(preflight_finished)
            return runtime

        outcome = run_local_task(
            Path("C:/project"),
            "Repair it",
            runtime_factory=runtime_factory,
            preflight_runner=preflight,
            service_runner=lambda workspace, task, *, endpoint, prepared: (
                self.assertIs(prepared, expected_prepared)
                or
                calls.append((workspace, task, endpoint)) or expected
            ),
        )

        self.assertIs(outcome, expected)
        self.assertTrue(runtime.entered)
        self.assertTrue(runtime.exited)
        self.assertEqual(
            calls,
            [(Path("C:/project"), "Repair it", "http://127.0.0.1:9090")],
        )

    def test_local_task_runner_stops_the_runtime_when_the_task_fails(self) -> None:
        from chatmpd.app import run_local_task

        runtime = _FakeRuntime()

        def fail(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("model failed")

        with self.assertRaisesRegex(RuntimeError, "model failed"):
            run_local_task(
                Path("C:/project"),
                "Repair it",
                runtime_factory=lambda: runtime,
                preflight_runner=lambda unused_workspace, unused_task: object(),
                service_runner=fail,
            )

        self.assertTrue(runtime.exited)

    def test_failed_preflight_never_constructs_or_loads_the_model_runtime(self) -> None:
        from chatmpd.app import run_local_task

        def forbidden_runtime() -> object:
            self.fail("runtime must not be constructed before preflight passes")

        with self.assertRaisesRegex(RuntimeError, "sandbox unavailable"):
            run_local_task(
                Path("C:/project"),
                "Repair it",
                runtime_factory=forbidden_runtime,
                preflight_runner=lambda unused_workspace, unused_task: (_ for _ in ()).throw(
                    RuntimeError("sandbox unavailable")
                ),
            )


if __name__ == "__main__":
    unittest.main()
