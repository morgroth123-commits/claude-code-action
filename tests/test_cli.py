from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from chatmpd.cli import main
from chatmpd.engine import CheckResult, RunResult
from chatmpd.project import ProjectProfile, SafeGitContext
from chatmpd.runtime import RuntimeDiagnostics
from chatmpd.sandbox import SandboxHealth, SandboxResult
from chatmpd.service import TaskOutcome, UnsupportedProjectError


def _supported_profile() -> ProjectProfile:
    command = ["/usr/bin/python3", "-m", "compileall", "-q", "."]
    return ProjectProfile(
        project_type="python-syntax",
        supported=True,
        detail="Python source project",
        manifest=[],
        manifest_truncated=False,
        git=SafeGitContext(False, None, None, False, "", "", None),
        verification_commands=[command],
        required_checks=[command],
    )


class CliTest(unittest.TestCase):
    def test_doctor_reports_local_readiness_without_starting_the_runtime(self) -> None:
        class DiagnosticRuntime:
            def diagnose(self) -> RuntimeDiagnostics:
                return RuntimeDiagnostics(
                    server_path=Path("C:/ChatMPD/llama-server.exe"),
                    model_path=Path("C:/ChatMPD/qwen-model.gguf"),
                    endpoint="http://127.0.0.1:8080",
                    endpoint_healthy=False,
                    endpoint_is_chatmpd=False,
                    eso_running=True,
                    mode="cpu-safe",
                    issues=(),
                )

            def start(self) -> None:
                raise AssertionError("doctor must not start the model")

            def __enter__(self) -> object:
                raise AssertionError("doctor must not enter the runtime context")

        class HealthySandbox:
            def probe(self) -> SandboxHealth:
                return SandboxHealth(True, "isolated checks are available")

        output = io.StringIO()
        with redirect_stdout(output):
            try:
                exit_code = main(
                    ["doctor"],
                    runtime_factory=DiagnosticRuntime,
                    sandbox_factory=HealthySandbox,
                )
            except (TypeError, SystemExit) as error:
                self.fail(f"doctor command was not available: {error}")

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("ChatMPD doctor", rendered)
        self.assertIn("llama-server.exe", rendered)
        self.assertIn("qwen-model.gguf", rendered)
        self.assertIn("Model endpoint: stopped", rendered)
        self.assertIn("Performance mode: cpu-safe (game detected)", rendered)
        self.assertIn("Sandbox: ready - isolated checks are available", rendered)
        self.assertIn("Overall: ready", rendered)

    def test_doctor_returns_attention_when_local_requirements_are_unavailable(self) -> None:
        class UnavailableRuntime:
            def diagnose(self) -> RuntimeDiagnostics:
                return RuntimeDiagnostics(
                    server_path=None,
                    model_path=None,
                    endpoint="http://127.0.0.1:8080",
                    endpoint_healthy=True,
                    endpoint_is_chatmpd=False,
                    eso_running=False,
                    mode="gpu-auto",
                    issues=(
                        "llama-server.exe was not found",
                        "local model was not found",
                    ),
                )

            def start(self) -> None:
                raise AssertionError("doctor must not start the model")

        class UnavailableSandbox:
            def probe(self) -> SandboxHealth:
                return SandboxHealth(False, "WSL sandbox is unavailable")

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                ["doctor"],
                runtime_factory=UnavailableRuntime,
                sandbox_factory=UnavailableSandbox,
            )

        rendered = output.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn("llama.cpp server: missing", rendered)
        self.assertIn("Local model: missing", rendered)
        self.assertIn("Model endpoint: occupied by another server", rendered)
        self.assertIn("Performance mode: gpu-auto (game not detected)", rendered)
        self.assertIn("Sandbox: unavailable - WSL sandbox is unavailable", rendered)
        self.assertIn("Overall: attention needed", rendered)

    def test_doctor_reports_a_preexisting_chatmpd_endpoint_as_busy(self) -> None:
        class RunningRuntime:
            def diagnose(self) -> RuntimeDiagnostics:
                return RuntimeDiagnostics(
                    server_path=Path("C:/ChatMPD/llama-server.exe"),
                    model_path=Path("C:/ChatMPD/qwen-model.gguf"),
                    endpoint="http://127.0.0.1:8080",
                    endpoint_healthy=True,
                    endpoint_is_chatmpd=True,
                    eso_running=False,
                    mode="gpu-auto",
                    issues=(),
                )

        class HealthySandbox:
            def probe(self) -> SandboxHealth:
                return SandboxHealth(True, "isolated checks are available")

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                ["doctor"],
                runtime_factory=RunningRuntime,
                sandbox_factory=HealthySandbox,
            )

        rendered = output.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn(
            "Model endpoint: occupied by another ChatMPD process", rendered
        )
        self.assertIn("Overall: attention needed", rendered)

    def test_doctor_converts_probe_errors_to_plain_output(self) -> None:
        class BrokenRuntime:
            def diagnose(self) -> RuntimeDiagnostics:
                raise OSError("runtime discovery failed")

        class ForbiddenSandbox:
            def probe(self) -> SandboxHealth:
                raise AssertionError("sandbox probe should not follow a discovery failure")

        errors = io.StringIO()
        with redirect_stderr(errors):
            try:
                exit_code = main(
                    ["doctor"],
                    runtime_factory=BrokenRuntime,
                    sandbox_factory=ForbiddenSandbox,
                )
            except OSError as error:
                self.fail(f"doctor error escaped the CLI: {error}")

        self.assertEqual(exit_code, 3)
        self.assertIn(
            "Doctor could not complete: OSError: runtime discovery failed",
            errors.getvalue(),
        )

    def test_run_uses_managed_runtime_and_prints_the_task_outcome(self) -> None:
        preflight_finished = False
        expected_prepared = object()

        class ManagedRuntime:
            endpoint = "http://127.0.0.1:9090"

            def __init__(self) -> None:
                self.entered = False
                self.exited = False

            def __enter__(self) -> "ManagedRuntime":
                self_case.assertTrue(preflight_finished)
                self.entered = True
                return self

            def __exit__(self, *_error: object) -> None:
                self.exited = True

        self_case = self
        runtime = ManagedRuntime()
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            state_file = workspace / ".chatmpd" / "runs" / "run-1" / "run.json"
            result = RunResult(
                status="succeeded",
                summary="Repaired calculator addition.",
                changed_files=["calculator.py"],
                checks=[
                    CheckResult(
                        argv=["/usr/bin/python3", "-m", "compileall", "-q", "."],
                        exit_code=1,
                        sequence=2,
                        stdout="",
                        stderr="syntax error",
                    ),
                    CheckResult(
                        argv=["/usr/bin/python3", "-m", "compileall", "-q", "."],
                        exit_code=0,
                        sequence=4,
                        stdout="",
                        stderr="",
                    ),
                ],
                state_file=state_file,
            )
            profile = _supported_profile()

            def run_task(
                received_workspace: Path,
                received_task: str,
                *,
                endpoint: str,
                prepared: object,
            ) -> TaskOutcome:
                self.assertTrue(runtime.entered)
                self.assertIs(prepared, expected_prepared)
                self.assertEqual(received_workspace, workspace.resolve())
                self.assertEqual(received_task, "Fix calculator addition")
                self.assertEqual(endpoint, ManagedRuntime.endpoint)
                return TaskOutcome(profile, result, ("chatmpd-local",))

            def preflight(
                received_workspace: Path, received_task: str
            ) -> object:
                nonlocal preflight_finished
                self.assertEqual(received_workspace, workspace.resolve())
                self.assertEqual(received_task, "Fix calculator addition")
                preflight_finished = True
                return expected_prepared

            output = io.StringIO()
            with redirect_stdout(output):
                try:
                    exit_code = main(
                        [
                            "run",
                            "--workspace",
                            str(workspace),
                            "--task",
                            "Fix calculator addition",
                        ],
                        runtime_factory=lambda: runtime,
                        preflight_runner=preflight,
                        task_runner=run_task,
                    )
                except (TypeError, SystemExit) as error:
                    self.fail(f"run command was not available: {error}")

        rendered = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertTrue(runtime.exited)
        self.assertIn("ChatMPD run", rendered)
        self.assertIn("Status: SUCCEEDED", rendered)
        self.assertIn("Summary: Repaired calculator addition.", rendered)
        self.assertIn("Changed files (1):", rendered)
        self.assertIn("calculator.py", rendered)
        self.assertIn("Checks (2):", rendered)
        self.assertIn("FAIL (exit 1): /usr/bin/python3 -m compileall -q .", rendered)
        self.assertIn("PASS (exit 0): /usr/bin/python3 -m compileall -q .", rendered)
        self.assertIn(f"Run record: {state_file}", rendered)

    def test_run_returns_failure_and_plain_empty_sections_for_a_failed_task(self) -> None:
        class ManagedRuntime:
            endpoint = "http://127.0.0.1:8080"

            def __enter__(self) -> "ManagedRuntime":
                return self

            def __exit__(self, *_error: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            result = RunResult(
                status="failed",
                summary="No safe repair was found.",
                changed_files=[],
                checks=[],
                state_file=workspace / ".chatmpd" / "runs" / "run-2" / "run.json",
            )

            def run_task(
                received_workspace: Path,
                received_task: str,
                *,
                endpoint: str,
            ) -> TaskOutcome:
                return TaskOutcome(_supported_profile(), result, ("chatmpd-local",))

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "run",
                        "--workspace",
                        str(workspace),
                        "--task",
                        "Attempt a safe repair",
                    ],
                    runtime_factory=ManagedRuntime,
                    task_runner=run_task,
                )

        rendered = output.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertIn("Status: FAILED", rendered)
        self.assertIn("Summary: No safe repair was found.", rendered)
        self.assertIn("Changed files: none", rendered)
        self.assertIn("Checks: none", rendered)

    def test_run_rejects_a_missing_workspace_before_constructing_the_runtime(self) -> None:
        def forbidden_runtime() -> object:
            raise AssertionError("invalid input must not construct the model runtime")

        with tempfile.TemporaryDirectory() as temporary_directory:
            missing_workspace = Path(temporary_directory) / "missing"
            errors = io.StringIO()
            with redirect_stderr(errors):
                try:
                    exit_code = main(
                        [
                            "run",
                            "--workspace",
                            str(missing_workspace),
                            "--task",
                            "Fix the project",
                        ],
                        runtime_factory=forbidden_runtime,
                    )
                except AssertionError as error:
                    self.fail(str(error))

        self.assertEqual(exit_code, 2)
        self.assertIn("Cannot run task: workspace is not an existing directory", errors.getvalue())

    def test_run_rejects_blank_task_text_before_constructing_the_runtime(self) -> None:
        def forbidden_runtime() -> object:
            raise AssertionError("blank input must not construct the model runtime")

        with tempfile.TemporaryDirectory() as temporary_directory:
            errors = io.StringIO()
            with redirect_stderr(errors):
                try:
                    exit_code = main(
                        [
                            "run",
                            "--workspace",
                            temporary_directory,
                            "--task",
                            "   ",
                        ],
                        runtime_factory=forbidden_runtime,
                    )
                except AssertionError as error:
                    self.fail(str(error))

        self.assertEqual(exit_code, 2)
        self.assertIn("Cannot run task: task text is empty", errors.getvalue())

    def test_run_preflights_an_unsupported_project_before_custom_runtime(self) -> None:
        runtime_constructed = False

        def forbidden_runtime() -> object:
            nonlocal runtime_constructed
            runtime_constructed = True
            raise AssertionError(
                "unsupported project must not construct the model runtime"
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            errors = io.StringIO()
            with redirect_stderr(errors):
                exit_code = main(
                    [
                        "run",
                        "--workspace",
                        temporary_directory,
                        "--task",
                        "Fix the project",
                    ],
                    runtime_factory=forbidden_runtime,
                )

        self.assertFalse(runtime_constructed)
        self.assertEqual(exit_code, 2)
        self.assertIn("Cannot run task:", errors.getvalue())

    def test_run_reports_a_local_runtime_startup_failure_with_exit_code_three(self) -> None:
        class UnavailableRuntime:
            def __enter__(self) -> object:
                raise RuntimeError("local llama model is missing")

            def __exit__(self, *_error: object) -> None:
                return None

        def forbidden_task_runner(*_args: object, **_kwargs: object) -> TaskOutcome:
            raise AssertionError("task must not run when the model cannot start")

        with tempfile.TemporaryDirectory() as temporary_directory:
            errors = io.StringIO()
            with redirect_stderr(errors):
                try:
                    exit_code = main(
                        [
                            "run",
                            "--workspace",
                            temporary_directory,
                            "--task",
                            "Fix the project",
                        ],
                        runtime_factory=UnavailableRuntime,
                        task_runner=forbidden_task_runner,
                    )
                except RuntimeError as error:
                    self.fail(f"runtime failure escaped the CLI: {error}")

        self.assertEqual(exit_code, 3)
        self.assertIn(
            "Local runtime is unavailable: local llama model is missing",
            errors.getvalue(),
        )

    def test_run_converts_unexpected_runtime_errors_to_plain_output(self) -> None:
        class UnavailableRuntime:
            def __enter__(self) -> object:
                raise OSError("could not launch llama-server")

            def __exit__(self, *_error: object) -> None:
                return None

        with tempfile.TemporaryDirectory() as temporary_directory:
            errors = io.StringIO()
            with redirect_stderr(errors):
                try:
                    exit_code = main(
                        [
                            "run",
                            "--workspace",
                            temporary_directory,
                            "--task",
                            "Fix the project",
                        ],
                        runtime_factory=UnavailableRuntime,
                        preflight_runner=lambda unused_workspace, unused_task: object(),
                    )
                except OSError as error:
                    self.fail(f"runtime error escaped the CLI: {error}")

        self.assertEqual(exit_code, 3)
        self.assertIn(
            "Local runtime is unavailable: OSError: could not launch llama-server",
            errors.getvalue(),
        )

    def test_run_reports_an_unsupported_project_and_stops_the_runtime(self) -> None:
        class ManagedRuntime:
            endpoint = "http://127.0.0.1:8080"

            def __init__(self) -> None:
                self.exited = False

            def __enter__(self) -> "ManagedRuntime":
                return self

            def __exit__(self, *_error: object) -> None:
                self.exited = True

        runtime = ManagedRuntime()

        def unsupported_task(*_args: object, **_kwargs: object) -> TaskOutcome:
            raise UnsupportedProjectError("no safe verification check was found")

        with tempfile.TemporaryDirectory() as temporary_directory:
            errors = io.StringIO()
            with redirect_stderr(errors):
                exit_code = main(
                    [
                        "run",
                        "--workspace",
                        temporary_directory,
                        "--task",
                        "Fix the project",
                    ],
                    runtime_factory=lambda: runtime,
                    task_runner=unsupported_task,
                )

        self.assertEqual(exit_code, 2)
        self.assertTrue(runtime.exited)
        self.assertIn(
            "Cannot run task: no safe verification check was found",
            errors.getvalue(),
        )

    def test_run_reports_task_validation_errors_with_exit_code_two(self) -> None:
        class ManagedRuntime:
            endpoint = "http://127.0.0.1:8080"

            def __enter__(self) -> "ManagedRuntime":
                return self

            def __exit__(self, *_error: object) -> None:
                return None

        def invalid_task(*_args: object, **_kwargs: object) -> TaskOutcome:
            raise ValueError("task exceeds the local size limit")

        with tempfile.TemporaryDirectory() as temporary_directory:
            errors = io.StringIO()
            with redirect_stderr(errors):
                try:
                    exit_code = main(
                        [
                            "run",
                            "--workspace",
                            temporary_directory,
                            "--task",
                            "Fix the project",
                        ],
                        runtime_factory=ManagedRuntime,
                        task_runner=invalid_task,
                    )
                except ValueError as error:
                    self.fail(f"task validation error escaped the CLI: {error}")

        self.assertEqual(exit_code, 2)
        self.assertIn(
            "Cannot run task: task exceeds the local size limit",
            errors.getvalue(),
        )

    def test_run_reports_execution_errors_with_exit_code_one_and_stops_runtime(self) -> None:
        class ManagedRuntime:
            endpoint = "http://127.0.0.1:8080"

            def __init__(self) -> None:
                self.exited = False

            def __enter__(self) -> "ManagedRuntime":
                return self

            def __exit__(self, *_error: object) -> None:
                self.exited = True

        runtime = ManagedRuntime()

        def failed_task(*_args: object, **_kwargs: object) -> TaskOutcome:
            raise RuntimeError("the local model returned an invalid response")

        with tempfile.TemporaryDirectory() as temporary_directory:
            errors = io.StringIO()
            with redirect_stderr(errors):
                exit_code = main(
                    [
                        "run",
                        "--workspace",
                        temporary_directory,
                        "--task",
                        "Fix the project",
                    ],
                    runtime_factory=lambda: runtime,
                    task_runner=failed_task,
                )

        self.assertEqual(exit_code, 1)
        self.assertTrue(runtime.exited)
        self.assertIn(
            "Task could not finish: the local model returned an invalid response",
            errors.getvalue(),
        )

    def test_run_converts_unexpected_task_errors_to_plain_output(self) -> None:
        class ManagedRuntime:
            endpoint = "http://127.0.0.1:8080"

            def __enter__(self) -> "ManagedRuntime":
                return self

            def __exit__(self, *_error: object) -> None:
                return None

        def denied_task(*_args: object, **_kwargs: object) -> TaskOutcome:
            raise PermissionError("project write was denied")

        with tempfile.TemporaryDirectory() as temporary_directory:
            errors = io.StringIO()
            with redirect_stderr(errors):
                try:
                    exit_code = main(
                        [
                            "run",
                            "--workspace",
                            temporary_directory,
                            "--task",
                            "Fix the project",
                        ],
                        runtime_factory=ManagedRuntime,
                        task_runner=denied_task,
                    )
                except PermissionError as error:
                    self.fail(f"task error escaped the CLI: {error}")

        self.assertEqual(exit_code, 1)
        self.assertIn(
            "Task could not finish: PermissionError: project write was denied",
            errors.getvalue(),
        )

    def test_demo_command_runs_a_visible_offline_repair(self) -> None:
        class OfflineDemoRunner:
            def run(
                self,
                workspace: Path,
                argv: list[str],
                **_options: object,
            ) -> SandboxResult:
                repaired = "left + right" in (workspace / "calculator.py").read_text(
                    encoding="utf-8"
                )
                return SandboxResult(
                    status="completed",
                    argv=list(argv),
                    exit_code=0 if repaired else 1,
                    stdout="",
                    stderr="",
                    duration_seconds=0.01,
                    timed_out=False,
                    output_truncated=False,
                    snapshot_files=2,
                    snapshot_bytes=100,
                    error=None,
                )

        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory) / "demo-project"
            output = io.StringIO()

            with redirect_stdout(output):
                try:
                    exit_code = main(
                        ["demo", "--workspace", str(project)],
                        demo_command_runner=OfflineDemoRunner(),
                    )
                except TypeError as error:
                    self.fail(f"demo runner could not be injected: {error}")

            rendered = output.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("ChatMPD", rendered)
            self.assertIn("SUCCEEDED", rendered)
            self.assertIn("failed as expected", rendered)
            self.assertIn("passed after repair", rendered)
            self.assertIn("left + right", (project / "calculator.py").read_text())


if __name__ == "__main__":
    unittest.main()
