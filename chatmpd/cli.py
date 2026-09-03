from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from .engine import AgentEngine
from .model import ScriptedModel
from .policy import PermissionPolicy
from .runtime import LlamaCppRuntime
from .sandbox import SandboxRunner
from .service import (
    TaskOutcome,
    UnsupportedProjectError,
    prepare_project_task,
    run_project_task,
)


def _demo_check_command() -> list[str]:
    return [
        "/usr/bin/python3",
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
    ]


def _create_demo_project(workspace: Path) -> None:
    if workspace.exists() and any(workspace.iterdir()):
        raise RuntimeError(f"Demo workspace is not empty: {workspace}")
    (workspace / "tests").mkdir(parents=True, exist_ok=True)
    (workspace / "calculator.py").write_text(
        "def add(left, right):\n    return left - right\n",
        encoding="utf-8",
    )
    (workspace / "tests" / "test_calculator.py").write_text(
        "import unittest\n"
        "from calculator import add\n\n"
        "class CalculatorTest(unittest.TestCase):\n"
        "    def test_adds_two_numbers(self):\n"
        "        self.assertEqual(add(2, 3), 5)\n",
        encoding="utf-8",
    )


def _run_demo(workspace: Path, *, command_runner: Any | None = None) -> int:
    _create_demo_project(workspace)
    check = _demo_check_command()
    model = ScriptedModel(
        [
            {"kind": "plan", "steps": ["Run tests", "Repair", "Verify"]},
            {"kind": "tool", "name": "run_command", "arguments": {"argv": check}},
            {
                "kind": "tool",
                "name": "read_file",
                "arguments": {"path": "calculator.py"},
                "expect": {"last_exit_code_nonzero": True},
            },
            {
                "kind": "tool",
                "name": "write_file",
                "arguments": {
                    "path": "calculator.py",
                    "content": "def add(left, right):\n    return left + right\n",
                },
            },
            {"kind": "tool", "name": "run_command", "arguments": {"argv": check}},
            {
                "kind": "final",
                "outcome": "success",
                "summary": "Corrected addition and verified the project tests.",
                "expect": {"last_exit_code": 0},
            },
        ]
    )
    policy = PermissionPolicy(
        writable_paths=["calculator.py"],
        allowed_commands=[check],
        required_checks=[check],
    )
    result = AgentEngine(
        workspace,
        model,
        policy,
        command_runner=command_runner,
    ).run(
        "Fix the deliberately failing addition test"
    )
    print("ChatMPD - offline executable repair demo")
    print(f"Workspace: {workspace}")
    print(f"Status: {result.status.upper()}")
    if len(result.checks) >= 2:
        print(f"First check: failed as expected (exit {result.checks[0].exit_code})")
        print(f"Final check: passed after repair (exit {result.checks[-1].exit_code})")
    print(f"Changed: {', '.join(result.changed_files)}")
    print(f"Run record: {result.state_file}")
    return 0 if result.status == "succeeded" else 1


def _default_demo_workspace() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(tempfile.gettempdir()) / f"ChatMPD-demo-{stamp}"


def _run_doctor(
    runtime_factory: Callable[[], LlamaCppRuntime],
    sandbox_factory: Callable[[], SandboxRunner],
) -> int:
    try:
        diagnostics = runtime_factory().diagnose()
        sandbox = sandbox_factory().probe()
    except Exception as error:
        print(
            f"Doctor could not complete: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 3

    print("ChatMPD doctor")
    if diagnostics.server_path is None:
        print("llama.cpp server: missing")
    else:
        print(f"llama.cpp server: ready - {diagnostics.server_path}")
    if diagnostics.model_path is None:
        print("Local model: missing")
    else:
        print(f"Local model: ready - {diagnostics.model_path}")

    if diagnostics.endpoint_healthy and diagnostics.endpoint_is_chatmpd:
        print(
            "Model endpoint: occupied by another ChatMPD process - "
            f"{diagnostics.endpoint}"
        )
    elif diagnostics.endpoint_healthy:
        print(f"Model endpoint: occupied by another server - {diagnostics.endpoint}")
    else:
        print(f"Model endpoint: stopped - {diagnostics.endpoint} (will start when needed)")

    game_state = "game detected" if diagnostics.eso_running else "game not detected"
    print(f"Performance mode: {diagnostics.mode} ({game_state})")
    sandbox_state = "ready" if sandbox.available else "unavailable"
    print(f"Sandbox: {sandbox_state} - {sandbox.detail}")

    blocked = bool(diagnostics.issues) or not sandbox.available
    blocked = blocked or diagnostics.endpoint_healthy
    print(f"Overall: {'attention needed' if blocked else 'ready'}")
    return 1 if blocked else 0


def _run_live_task(
    workspace: Path,
    task: str,
    runtime_factory: Callable[[], LlamaCppRuntime],
    task_runner: Callable[..., TaskOutcome],
    preflight_runner: Callable[..., Any] | None = None,
) -> int:
    workspace = workspace.expanduser()
    if not workspace.is_dir():
        print(
            f"Cannot run task: workspace is not an existing directory: {workspace}",
            file=sys.stderr,
        )
        return 2
    if not task.strip():
        print("Cannot run task: task text is empty", file=sys.stderr)
        return 2

    resolved_workspace = workspace.resolve()
    prepared: Any | None = None
    if preflight_runner is not None:
        try:
            prepared = preflight_runner(resolved_workspace, task)
        except (UnsupportedProjectError, ValueError) as error:
            print(f"Cannot run task: {error}", file=sys.stderr)
            return 2
        except RuntimeError as error:
            print(f"Task could not finish: {error}", file=sys.stderr)
            return 1
        except Exception as error:
            print(
                f"Task could not finish: {type(error).__name__}: {error}",
                file=sys.stderr,
            )
            return 1

    try:
        with runtime_factory() as runtime:
            try:
                task_options: dict[str, Any] = {"endpoint": runtime.endpoint}
                if preflight_runner is not None:
                    task_options["prepared"] = prepared
                outcome = task_runner(resolved_workspace, task, **task_options)
            except (UnsupportedProjectError, ValueError) as error:
                print(f"Cannot run task: {error}", file=sys.stderr)
                return 2
            except RuntimeError as error:
                print(f"Task could not finish: {error}", file=sys.stderr)
                return 1
            except Exception as error:
                print(
                    f"Task could not finish: {type(error).__name__}: {error}",
                    file=sys.stderr,
                )
                return 1
    except RuntimeError as error:
        print(f"Local runtime is unavailable: {error}", file=sys.stderr)
        return 3
    except Exception as error:
        print(
            f"Local runtime is unavailable: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 3

    result = outcome.result
    print("ChatMPD run")
    print(f"Status: {result.status.upper()}")
    print(f"Summary: {result.summary}")
    if result.changed_files:
        print(f"Changed files ({len(result.changed_files)}):")
        for changed_file in result.changed_files:
            print(f"  {changed_file}")
    else:
        print("Changed files: none")
    if result.checks:
        print(f"Checks ({len(result.checks)}):")
        for check in result.checks:
            state = "PASS" if check.exit_code == 0 else "FAIL"
            print(f"  {state} (exit {check.exit_code}): {' '.join(check.argv)}")
    else:
        print("Checks: none")
    print(f"Run record: {result.state_file}")
    return 0 if result.status == "succeeded" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ChatMPD", description="Local-first autonomous coding agent"
    )
    subparsers = parser.add_subparsers(dest="command")
    demo = subparsers.add_parser("demo", help="Run a credential-free repair demo")
    demo.add_argument("--workspace", type=Path, default=None)
    subparsers.add_parser("doctor", help="Check local model and sandbox readiness")
    run = subparsers.add_parser("run", help="Run a task with the local model")
    run.add_argument("--workspace", type=Path, required=True)
    run.add_argument("--task", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runtime_factory: Callable[[], LlamaCppRuntime] | None = None,
    sandbox_factory: Callable[[], SandboxRunner] | None = None,
    preflight_runner: Callable[..., Any] | None = None,
    task_runner: Callable[..., TaskOutcome] | None = None,
    demo_command_runner: Any | None = None,
) -> int:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if not arguments:
        arguments = ["demo"]
    parsed = build_parser().parse_args(arguments)
    if parsed.command == "demo":
        workspace = parsed.workspace or _default_demo_workspace()
        return _run_demo(
            workspace.resolve(),
            command_runner=demo_command_runner,
        )
    if parsed.command == "doctor":
        return _run_doctor(
            runtime_factory or LlamaCppRuntime,
            sandbox_factory or SandboxRunner,
        )
    if parsed.command == "run":
        selected_preflight = preflight_runner
        if selected_preflight is None and task_runner is None:
            selected_preflight = prepare_project_task
        return _run_live_task(
            parsed.workspace,
            parsed.task,
            runtime_factory or LlamaCppRuntime,
            task_runner or run_project_task,
            selected_preflight,
        )
    return 2
