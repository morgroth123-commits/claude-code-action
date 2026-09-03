from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from chatmpd.engine import AgentEngine
from chatmpd.model import ScriptedModel
from chatmpd.policy import PermissionPolicy


class VerticalSliceTest(unittest.TestCase):
    def test_repairs_failing_code_and_verifies_after_the_edit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            (project / "tests").mkdir()
            (project / "calculator.py").write_text(
                "def add(left, right):\n    return left - right\n",
                encoding="utf-8",
            )
            (project / "tests" / "test_calculator.py").write_text(
                "import unittest\n"
                "from calculator import add\n\n"
                "class CalculatorTest(unittest.TestCase):\n"
                "    def test_adds_two_numbers(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n\n"
                "if __name__ == '__main__':\n"
                "    unittest.main()\n",
                encoding="utf-8",
            )

            check = [
                "/usr/bin/python3",
                "-m",
                "unittest",
                "discover",
                "-s",
                "tests",
            ]
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

            result = AgentEngine(project, model, policy).run(
                "Fix the failing addition test"
            )

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(result.changed_files, ["calculator.py"])
            self.assertEqual([check.exit_code for check in result.checks], [1, 0])
            self.assertIn("left + right", (project / "calculator.py").read_text())
            run_state = json.loads(result.state_file.read_text(encoding="utf-8"))
            self.assertEqual(run_state["status"], "succeeded")
            self.assertGreaterEqual(run_state["events_recorded"], 10)
            backup = result.state_file.parent / "backups" / "calculator.py"
            self.assertEqual(
                backup.read_text(encoding="utf-8"),
                "def add(left, right):\n    return left - right\n",
            )


if __name__ == "__main__":
    unittest.main()
