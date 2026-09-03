from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from chatmpd.llamacpp import ChatResponse, ToolCall
from chatmpd.sandbox import SandboxHealth
from chatmpd.service import run_project_task


class ScriptedProvider:
    def __init__(self, responses: list[ChatResponse]) -> None:
        self.responses = list(responses)

    def health(self) -> bool:
        return True

    def models(self) -> tuple[str, ...]:
        return ("chatmpd-local",)

    def chat(self, *unused: object, **also_unused: object) -> ChatResponse:
        return self.responses.pop(0)


class InspectingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(
        self, workspace: Path, argv: list[str], **unused: Any
    ) -> SimpleNamespace:
        self.calls.append(list(argv))
        repaired = "left + right" in (workspace / "calculator.py").read_text(
            encoding="utf-8"
        )
        return SimpleNamespace(
            status="completed",
            exit_code=0 if repaired else 1,
            stdout="compile check\n",
            stderr="",
            error=None,
        )


class ServiceTest(unittest.TestCase):
    def test_unavailable_sandbox_is_rejected_before_the_model_can_write(self) -> None:
        test_case = self

        class UnavailableRunner:
            def probe(self) -> SandboxHealth:
                return SandboxHealth(False, "isolated verification unavailable")

            def run(self, *_args: object, **_kwargs: object) -> object:
                test_case.fail("unavailable runner must never execute")

        class ForbiddenProvider:
            def health(self) -> bool:
                test_case.fail("model must not start before sandbox preflight")

        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            source = workspace / "calculator.py"
            source.write_text("answer = 41\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "isolated verification"):
                run_project_task(
                    workspace,
                    "Fix the calculator",
                    provider=ForbiddenProvider(),
                    command_runner=UnavailableRunner(),
                )

            self.assertEqual(source.read_text(encoding="utf-8"), "answer = 41\n")

    def test_profiles_routes_edits_and_requires_the_detected_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "calculator.py").write_text(
                "def add(left, right):\n    return left - right\n", encoding="utf-8"
            )
            provider = ScriptedProvider(
                [
                    ChatResponse("1. Read code\n2. Repair\n3. Verify", (), "stop"),
                    ChatResponse(
                        "",
                        (
                            ToolCall(
                                "read", "read_file", {"path": "calculator.py"}
                            ),
                        ),
                        "tool_calls",
                    ),
                    ChatResponse(
                        "",
                        (
                            ToolCall(
                                "write",
                                "write_file",
                                {
                                    "path": "calculator.py",
                                    "content": (
                                        "def add(left, right):\n    return left + right\n"
                                    ),
                                },
                            ),
                        ),
                        "tool_calls",
                    ),
                    ChatResponse(
                        "",
                        (
                            ToolCall(
                                "verify",
                                "run_command",
                                {
                                    "argv": [
                                        "/usr/bin/python3",
                                        "-m",
                                        "compileall",
                                        "-q",
                                        ".",
                                    ]
                                },
                            ),
                        ),
                        "tool_calls",
                    ),
                    ChatResponse(
                        "SUCCESS: Repaired and verified the calculator.", (), "stop"
                    ),
                ]
            )
            runner = InspectingRunner()

            outcome = run_project_task(
                workspace,
                "Fix calculator addition",
                provider=provider,
                command_runner=runner,
            )

            self.assertEqual(outcome.result.status, "succeeded")
            self.assertEqual(outcome.profile.project_type, "python-syntax")
            self.assertEqual(
                runner.calls,
                [["/usr/bin/python3", "-m", "compileall", "-q", "."]],
            )
            self.assertIn(
                "left + right",
                (workspace / "calculator.py").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
