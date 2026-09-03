from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from chatmpd.engine import AgentEngine
from chatmpd.model import ScriptedModel
from chatmpd.policy import PermissionPolicy


class EngineSafetyTest(unittest.TestCase):
    def test_run_command_is_delegated_to_the_injected_isolated_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            check = ["/usr/bin/python3", "-m", "unittest"]

            class RecordingRunner:
                def __init__(self) -> None:
                    self.calls: list[tuple[Path, list[str]]] = []

                def run(
                    self,
                    received_workspace: Path,
                    argv: list[str],
                    **unused: object,
                ) -> object:
                    self.calls.append((received_workspace, list(argv)))
                    return SimpleNamespace(
                        status="completed",
                        exit_code=0,
                        stdout="OK\n",
                        stderr="",
                        error=None,
                    )

            runner = RecordingRunner()
            model = ScriptedModel(
                [
                    {"kind": "plan", "steps": ["Verify"]},
                    {
                        "kind": "tool",
                        "name": "run_command",
                        "arguments": {"argv": check},
                    },
                    {
                        "kind": "final",
                        "outcome": "success",
                        "summary": "Verification passed in isolation.",
                    },
                ]
            )
            policy = PermissionPolicy(
                writable_paths=[], allowed_commands=[check], required_checks=[check]
            )

            result = AgentEngine(
                workspace, model, policy, command_runner=runner
            ).run("Verify")

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(runner.calls, [(workspace.resolve(), check)])

    def test_run_state_cannot_follow_a_chatmpd_link_outside_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            workspace = root / "project"
            outside = root / "outside"
            workspace.mkdir()
            outside.mkdir()
            try:
                (workspace / ".chatmpd").symlink_to(
                    outside, target_is_directory=True
                )
            except OSError as error:
                self.skipTest(f"Directory links are unavailable: {error}")

            with self.assertRaisesRegex(PermissionError, "run state"):
                AgentEngine(
                    workspace,
                    ScriptedModel(
                        [{"kind": "plan", "steps": ["Inspect the project"]}]
                    ),
                    PermissionPolicy([], [], []),
                ).run("Inspect this project")

            self.assertEqual(list(outside.iterdir()), [])

    def test_write_file_preserves_lf_bytes_on_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            check = ["/usr/bin/python3", "-m", "compileall", "-q", "."]

            class PassingRunner:
                def run(self, *_args: object, **_kwargs: object) -> object:
                    return SimpleNamespace(
                        status="completed",
                        exit_code=0,
                        stdout="",
                        stderr="",
                        error=None,
                    )

            result = AgentEngine(
                workspace,
                ScriptedModel(
                    [
                        {"kind": "plan", "steps": ["Write and verify"]},
                        {
                            "kind": "tool",
                            "name": "write_file",
                            "arguments": {
                                "path": "line_endings.py",
                                "content": "first = 1\nsecond = 2\n",
                            },
                        },
                        {
                            "kind": "tool",
                            "name": "run_command",
                            "arguments": {"argv": check},
                        },
                        {
                            "kind": "final",
                            "outcome": "success",
                            "summary": "Verified.",
                        },
                    ]
                ),
                PermissionPolicy(["line_endings.py"], [check], [check]),
                command_runner=PassingRunner(),
            ).run("Write the source file")

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(
                (workspace / "line_endings.py").read_bytes(),
                b"first = 1\nsecond = 2\n",
            )

    def test_zero_discovered_unittests_cannot_satisfy_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            check = [
                "/usr/bin/python3",
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
            ]

            class EmptySuiteRunner:
                def run(self, *_args: object, **_kwargs: object) -> object:
                    return SimpleNamespace(
                        status="completed",
                        exit_code=0,
                        stdout="",
                        stderr="Ran 0 tests in 0.000s\n\nOK\n",
                        error=None,
                    )

            result = AgentEngine(
                workspace,
                ScriptedModel(
                    [
                        {"kind": "plan", "steps": ["Run tests"]},
                        {
                            "kind": "tool",
                            "name": "run_command",
                            "arguments": {"argv": check},
                        },
                        {
                            "kind": "final",
                            "outcome": "success",
                            "summary": "Tests passed.",
                        },
                        {
                            "kind": "final",
                            "outcome": "failed",
                            "summary": "No tests were discovered.",
                        },
                    ]
                ),
                PermissionPolicy([], [check], [check]),
                command_runner=EmptySuiteRunner(),
            ).run("Verify the project tests")

            self.assertEqual(result.status, "failed")
            self.assertEqual(len(result.checks), 1)
            self.assertNotEqual(result.checks[0].exit_code, 0)
            self.assertIn("No tests were discovered", result.checks[0].stderr)

    def test_model_failure_is_persisted_before_the_error_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            model = ScriptedModel([])
            policy = PermissionPolicy(
                writable_paths=[], allowed_commands=[], required_checks=[]
            )

            with self.assertRaisesRegex(RuntimeError, "ran out of turns"):
                AgentEngine(workspace, model, policy).run("Inspect this project")

            state_files = list((workspace / ".chatmpd" / "runs").glob("*/run.json"))
            self.assertEqual(len(state_files), 1)
            state = json.loads(state_files[0].read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "failed")
            self.assertIn("ScriptedModel", state["summary"])
            self.assertGreaterEqual(state["events_recorded"], 2)

    def test_secret_files_are_not_read_or_copied_into_run_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            secret = "CHATMPD_TEST_SECRET=do-not-log-this"
            (workspace / ".env").write_text(secret, encoding="utf-8")
            model = ScriptedModel(
                [
                    {"kind": "plan", "steps": ["Inspect configuration"]},
                    {
                        "kind": "tool",
                        "name": "read_file",
                        "arguments": {"path": ".env"},
                    },
                ]
            )
            policy = PermissionPolicy(
                writable_paths=[], allowed_commands=[], required_checks=[]
            )

            with self.assertRaisesRegex(PermissionError, "sensitive"):
                AgentEngine(workspace, model, policy).run("Inspect this project")

            event_files = list(
                (workspace / ".chatmpd" / "runs").glob("*/events.jsonl")
            )
            self.assertEqual(len(event_files), 1)
            self.assertNotIn(secret, event_files[0].read_text(encoding="utf-8"))

    def test_secret_directories_are_protected_even_for_ordinary_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            protected = workspace / "secrets" / "notes.txt"
            protected.parent.mkdir()
            protected.write_text("do-not-read", encoding="utf-8")
            model = ScriptedModel(
                [
                    {"kind": "plan", "steps": ["Inspect secrets"]},
                    {
                        "kind": "tool",
                        "name": "read_file",
                        "arguments": {"path": "secrets/notes.txt"},
                    },
                ]
            )

            with self.assertRaisesRegex(PermissionError, "protected"):
                AgentEngine(
                    workspace,
                    model,
                    PermissionPolicy([], [], []),
                ).run("Inspect this project")

    def test_read_file_observation_matches_exact_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            source_bytes = b"first = 1\r\nsecond = 2\r\n"
            (workspace / "source.py").write_bytes(source_bytes)

            class ObservingModel:
                def __init__(self) -> None:
                    self.position = 0
                    self.observation: dict[str, object] | None = None

                def next_turn(self, context: dict[str, object]) -> dict[str, object]:
                    self.position += 1
                    if self.position == 1:
                        return {"kind": "plan", "steps": ["Read source.py"]}
                    if self.position == 2:
                        return {
                            "kind": "tool",
                            "name": "read_file",
                            "arguments": {"path": "source.py"},
                        }
                    self.observation = next(
                        event["data"]["result"]
                        for event in context["events"]  # type: ignore[union-attr]
                        if event["type"] == "tool_finished"
                    )
                    return {
                        "kind": "final",
                        "outcome": "success",
                        "summary": "Inspected the source.",
                    }

            model = ObservingModel()
            result = AgentEngine(
                workspace,
                model,
                PermissionPolicy([], [], []),
            ).run("Inspect source.py")

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(
                model.observation,
                {
                    "path": "source.py",
                    "content": "first = 1\r\nsecond = 2\r\n",
                    "bytes": 23,
                    "sha256": (
                        "7cc55a1f267ef97cd8c8a430125ca2e0459048b692adfc3d37d289ff30e84f38"
                    ),
                },
            )

    def test_source_contents_reach_the_model_but_are_not_persisted_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            source_token = "ordinary_source_token_that_should_remain_ephemeral"
            source_text = f"{source_token} = 42\n"
            (workspace / "source.py").write_bytes(source_text.encode("utf-8"))

            class ObservingModel:
                def __init__(self) -> None:
                    self.position = 0

                def next_turn(self, context: dict[str, object]) -> dict[str, object]:
                    self.position += 1
                    if self.position == 1:
                        return {"kind": "plan", "steps": ["Read source.py"]}
                    if self.position == 2:
                        return {
                            "kind": "tool",
                            "name": "read_file",
                            "arguments": {"path": "source.py"},
                        }
                    observed = any(
                        event.get("type") == "tool_finished"
                        and event.get("data", {}).get("result", {}).get("content")
                        == source_text
                        for event in context.get("events", [])  # type: ignore[union-attr]
                    )
                    if not observed:
                        raise AssertionError("The model did not receive the file observation")
                    return {
                        "kind": "final",
                        "outcome": "success",
                        "summary": "Inspected the source.",
                    }

            policy = PermissionPolicy(
                writable_paths=[], allowed_commands=[], required_checks=[]
            )

            result = AgentEngine(workspace, ObservingModel(), policy).run(
                "Inspect source.py"
            )

            persisted = result.state_file.with_name("events.jsonl").read_text(
                encoding="utf-8"
            ) + result.state_file.read_text(encoding="utf-8")
            self.assertNotIn(source_token, persisted)

    def test_command_output_is_ephemeral_and_not_duplicated_in_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            output_token = "command_output_token_that_should_not_be_persisted"
            check = ["/usr/bin/python3", "-m", "unittest"]

            class OutputRunner:
                def run(self, *unused: object, **also_unused: object) -> object:
                    return SimpleNamespace(
                        status="completed",
                        exit_code=0,
                        stdout=f"{output_token}\n",
                        stderr="",
                        error=None,
                    )

            model = ScriptedModel(
                [
                    {"kind": "plan", "steps": ["Verify"]},
                    {
                        "kind": "tool",
                        "name": "run_command",
                        "arguments": {"argv": check},
                    },
                    {
                        "kind": "final",
                        "outcome": "success",
                        "summary": "Verified.",
                        "expect": {"last_exit_code": 0},
                    },
                ]
            )
            policy = PermissionPolicy(
                writable_paths=[], allowed_commands=[check], required_checks=[check]
            )

            result = AgentEngine(
                workspace, model, policy, command_runner=OutputRunner()
            ).run("Verify")

            persisted = result.state_file.with_name("events.jsonl").read_text(
                encoding="utf-8"
            ) + result.state_file.read_text(encoding="utf-8")
            self.assertNotIn(output_token, persisted)

    def test_oversized_file_is_rejected_before_reading_it_into_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "large.txt").write_bytes(b"x" * (262_144 + 1))
            model = ScriptedModel(
                [
                    {"kind": "plan", "steps": ["Inspect large.txt"]},
                    {
                        "kind": "tool",
                        "name": "read_file",
                        "arguments": {"path": "large.txt"},
                    },
                    {
                        "kind": "final",
                        "outcome": "failed",
                        "summary": "The file is too large to inspect safely.",
                        "expect": {"last_tool_error_type": "RuntimeError"},
                    },
                ]
            )
            policy = PermissionPolicy([], [], [])

            with patch.object(
                Path,
                "read_text",
                side_effect=AssertionError("read_text must not be called"),
            ):
                result = AgentEngine(workspace, model, policy).run("Inspect large.txt")

            self.assertEqual(result.status, "failed")

    def test_recoverable_tool_failure_is_returned_to_the_model_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "actual.py").write_text("answer = 42\n", encoding="utf-8")
            model = ScriptedModel(
                [
                    {"kind": "plan", "steps": ["Inspect the source"]},
                    {
                        "kind": "tool",
                        "name": "read_file",
                        "arguments": {"path": "missing.py"},
                    },
                    {
                        "kind": "tool",
                        "name": "read_file",
                        "arguments": {"path": "actual.py"},
                        "expect": {"last_tool_error_type": "FileNotFoundError"},
                    },
                    {
                        "kind": "final",
                        "outcome": "success",
                        "summary": "Recovered from the missing path and inspected the source.",
                    },
                ]
            )
            policy = PermissionPolicy(
                writable_paths=[], allowed_commands=[], required_checks=[]
            )

            result = AgentEngine(workspace, model, policy).run("Inspect actual.py")

            self.assertEqual(result.status, "succeeded")
            events_file = result.state_file.with_name("events.jsonl")
            events = [
                json.loads(line)
                for line in events_file.read_text(encoding="utf-8").splitlines()
            ]
            failures = [event for event in events if event["type"] == "tool_failed"]
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0]["data"]["error_type"], "FileNotFoundError")

    def test_workspace_write_rule_allows_new_code_but_not_protected_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            check = [
                "/usr/bin/python3",
                "-c",
                (
                    "from pathlib import Path; "
                    "raise SystemExit(0 if Path('src/new_module.py').read_text() "
                    "== 'value = 42\\n' else 1)"
                ),
            ]
            model = ScriptedModel(
                [
                    {"kind": "plan", "steps": ["Create the requested module"]},
                    {
                        "kind": "tool",
                        "name": "write_file",
                        "arguments": {
                            "path": "src/new_module.py",
                            "content": "value = 42\n",
                        },
                    },
                    {
                        "kind": "tool",
                        "name": "run_command",
                        "arguments": {"argv": check},
                    },
                    {
                        "kind": "final",
                        "outcome": "success",
                        "summary": "Created the module.",
                    },
                ]
            )
            policy = PermissionPolicy(
                writable_paths=["**"],
                allowed_commands=[check],
                required_checks=[check],
            )

            result = AgentEngine(workspace, model, policy).run("Create a module")

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(
                (workspace / "src" / "new_module.py").read_text(encoding="utf-8"),
                "value = 42\n",
            )

            protected_model = ScriptedModel(
                [
                    {"kind": "plan", "steps": ["Overwrite internal state"]},
                    {
                        "kind": "tool",
                        "name": "write_file",
                        "arguments": {
                            "path": ".chatmpd/settings.json",
                            "content": "{}",
                        },
                    },
                ]
            )
            with self.assertRaisesRegex(PermissionError, "protected"):
                AgentEngine(workspace, protected_model, policy).run(
                    "Overwrite internal state"
                )

    def test_windows_aliases_cannot_bypass_protected_directory_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / ".git").mkdir()
            (workspace / ".git" / "config").write_text(
                "credential = must-not-enter-model-context\n", encoding="utf-8"
            )
            policy = PermissionPolicy(
                writable_paths=["**"], allowed_commands=[], required_checks=[]
            )

            for alias in (".git./config", ".git /config"):
                with self.subTest(alias=alias):
                    model = ScriptedModel(
                        [
                            {"kind": "plan", "steps": ["Inspect Git configuration"]},
                            {
                                "kind": "tool",
                                "name": "read_file",
                                "arguments": {"path": alias},
                            },
                        ]
                    )
                    with self.assertRaisesRegex(PermissionError, "protected"):
                        AgentEngine(workspace, model, policy).run("Inspect Git")

    def test_symlink_cannot_redirect_an_allowed_write_into_protected_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / ".git").mkdir()
            protected = workspace / ".git" / "config"
            protected.write_text("original\n", encoding="utf-8")
            alias = workspace / "allowed.py"
            try:
                alias.symlink_to(protected)
            except OSError as error:
                self.skipTest(f"Creating a test symlink is unavailable: {error}")
            model = ScriptedModel(
                [
                    {"kind": "plan", "steps": ["Write the module"]},
                    {
                        "kind": "tool",
                        "name": "write_file",
                        "arguments": {
                            "path": "allowed.py",
                            "content": "overwritten\n",
                        },
                    },
                ]
            )
            policy = PermissionPolicy(
                writable_paths=["**"], allowed_commands=[], required_checks=[]
            )

            with self.assertRaisesRegex(PermissionError, "link|protected"):
                AgentEngine(workspace, model, policy).run("Write the module")

            self.assertEqual(protected.read_text(encoding="utf-8"), "original\n")

    def test_extended_windows_device_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            policy = PermissionPolicy(
                writable_paths=["**"], allowed_commands=[], required_checks=[]
            )
            for device_name in ("CONIN$", "CONOUT$", "COM¹", "LPT³"):
                with self.subTest(device_name=device_name):
                    model = ScriptedModel(
                        [
                            {"kind": "plan", "steps": ["Write a file"]},
                            {
                                "kind": "tool",
                                "name": "write_file",
                                "arguments": {
                                    "path": device_name,
                                    "content": "unsafe\n",
                                },
                            },
                        ]
                    )
                    with self.assertRaisesRegex(PermissionError, "protected"):
                        AgentEngine(workspace, model, policy).run("Write a file")

    def test_second_run_cannot_reuse_the_first_runs_passing_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            check = ["/usr/bin/python3", "-c", "raise SystemExit(0)"]
            model = ScriptedModel(
                [
                    {"kind": "plan", "steps": ["Verify"]},
                    {
                        "kind": "tool",
                        "name": "run_command",
                        "arguments": {"argv": check},
                    },
                    {
                        "kind": "final",
                        "outcome": "success",
                        "summary": "First run verified.",
                    },
                    {"kind": "plan", "steps": ["Verify again"]},
                    {
                        "kind": "final",
                        "outcome": "success",
                        "summary": "Second run tried to reuse stale verification.",
                    },
                    {
                        "kind": "final",
                        "outcome": "failed",
                        "summary": "Second run had no fresh verification.",
                    },
                ]
            )
            policy = PermissionPolicy(
                writable_paths=[], allowed_commands=[check], required_checks=[check]
            )
            engine = AgentEngine(workspace, model, policy)

            first = engine.run("First task")
            second = engine.run("Second task")

            self.assertEqual(first.status, "succeeded")
            self.assertEqual(second.status, "failed")
            self.assertEqual(second.checks, [])
            events = [
                json.loads(line)
                for line in second.state_file.with_name("events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(events[0]["sequence"], 1)
            self.assertEqual(events[0]["data"]["task"], "Second task")

    def test_a_write_cannot_succeed_without_a_configured_verification_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            model = ScriptedModel(
                [
                    {"kind": "plan", "steps": ["Create code"]},
                    {
                        "kind": "tool",
                        "name": "write_file",
                        "arguments": {"path": "main.py", "content": "value = 1\n"},
                    },
                    {
                        "kind": "final",
                        "outcome": "success",
                        "summary": "Created code without checking it.",
                    },
                    {
                        "kind": "final",
                        "outcome": "failed",
                        "summary": "No verification check was configured.",
                    },
                ]
            )
            policy = PermissionPolicy(
                writable_paths=["**"], allowed_commands=[], required_checks=[]
            )

            result = AgentEngine(workspace, model, policy).run("Create code")

            self.assertEqual(result.status, "failed")
            events = result.state_file.with_name("events.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn("completion_rejected", events)

    def test_a_noncheck_command_invalidates_earlier_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "app.py").write_text("value = 1\n", encoding="utf-8")
            check = [
                "/usr/bin/python3",
                "-c",
                (
                    "from pathlib import Path; "
                    "raise SystemExit(0 if Path('app.py').read_text() "
                    "== 'value = 1\\n' else 1)"
                ),
            ]
            breaker = [
                "/usr/bin/python3",
                "-c",
                "from pathlib import Path; Path('app.py').write_text('broken\\n')",
            ]
            model = ScriptedModel(
                [
                    {"kind": "plan", "steps": ["Verify then inspect"]},
                    {
                        "kind": "tool",
                        "name": "run_command",
                        "arguments": {"argv": check},
                    },
                    {
                        "kind": "tool",
                        "name": "run_command",
                        "arguments": {"argv": breaker},
                    },
                    {
                        "kind": "final",
                        "outcome": "success",
                        "summary": "Claimed success after a later command.",
                    },
                    {
                        "kind": "final",
                        "outcome": "failed",
                        "summary": "Verification was stale.",
                    },
                ]
            )
            policy = PermissionPolicy(
                writable_paths=[],
                allowed_commands=[check, breaker],
                required_checks=[check],
            )

            result = AgentEngine(workspace, model, policy).run("Verify app.py")

            self.assertEqual(result.status, "failed")


if __name__ == "__main__":
    unittest.main()
