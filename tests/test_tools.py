from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from chatmpd.engine import AgentEngine
from chatmpd.policy import PermissionPolicy


class ListObservingModel:
    def __init__(self) -> None:
        self.position = 0

    def next_turn(self, context: dict[str, Any]) -> dict[str, Any]:
        self.position += 1
        if self.position == 1:
            return {"kind": "plan", "steps": ["List project files"]}
        if self.position == 2:
            return {
                "kind": "tool",
                "name": "list_files",
                "arguments": {"path": "."},
            }
        result = next(
            event["data"]["result"]
            for event in reversed(context["events"])
            if event["type"] == "tool_finished"
        )
        paths = [entry["path"] for entry in result["files"]]
        if paths != ["README.md", "src/main.py", "tests/test_main.py"]:
            raise AssertionError(f"Unexpected safe file inventory: {paths!r}")
        return {
            "kind": "final",
            "outcome": "success",
            "summary": "Inventoried the project.",
        }


class ToolTest(unittest.TestCase):
    def test_list_files_returns_a_bounded_inventory_without_secrets_or_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            for relative in ("README.md", "src/main.py", "tests/test_main.py"):
                path = workspace / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative, encoding="utf-8")
            (workspace / ".env").write_text("SECRET=hidden", encoding="utf-8")
            (workspace / ".git").mkdir()
            (workspace / ".git" / "config").write_text("hidden", encoding="utf-8")
            (workspace / "secrets").mkdir()
            (workspace / "secrets" / "notes.txt").write_text(
                "hidden", encoding="utf-8"
            )

            result = AgentEngine(
                workspace,
                ListObservingModel(),
                PermissionPolicy([], [], []),
            ).run("Inspect the project")

            self.assertEqual(result.status, "succeeded")


if __name__ == "__main__":
    unittest.main()
