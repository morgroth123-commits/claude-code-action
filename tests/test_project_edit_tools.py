from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from chatmpd.engine import AgentEngine
from chatmpd.local_model import TOOLS
from chatmpd.model import ScriptedModel
from chatmpd.policy import PermissionPolicy


class _PassingRunner:
    def run(self, *_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(
            status="completed",
            exit_code=0,
            stdout="OK\n",
            stderr="",
            error=None,
        )


class ExtendedProjectToolTest(unittest.TestCase):
    def test_local_model_exposes_search_and_surgical_replace(self) -> None:
        names = {tool["function"]["name"] for tool in TOOLS}
        self.assertIn("search_text", names)
        self.assertIn("replace_text", names)

    def test_search_is_bounded_and_skips_sensitive_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.py").write_text("needle one\nneedle two\n", encoding="utf-8")
            (root / ".env").write_text("needle SECRET\n", encoding="utf-8")
            model = ScriptedModel([
                {"kind": "plan", "steps": ["Search"]},
                {"kind": "tool", "name": "search_text", "arguments": {"query": "needle"}},
                {"kind": "final", "outcome": "success", "summary": "Searched."},
            ])
            engine = AgentEngine(root, model, PermissionPolicy([], [], []))
            result = engine.run("Find needle")

            self.assertEqual(result.status, "succeeded")
            finished = next(
                event for event in engine.events
                if event["type"] == "tool_finished"
            )
            matches = finished["data"]["result"]["matches"]
            self.assertEqual([match["line"] for match in matches], [1, 2])
            self.assertTrue(all(match["path"] == "a.py" for match in matches))
            events_text = Path(result.state_file).with_name("events.jsonl").read_text("utf-8")
            self.assertNotIn("needle one", events_text)
            self.assertNotIn("SECRET", events_text)

    def test_search_caps_result_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "many.txt").write_text("\n".join(["hit"] * 150), encoding="utf-8")
            model = ScriptedModel([
                {"kind": "plan", "steps": ["Search"]},
                {"kind": "tool", "name": "search_text", "arguments": {"query": "hit"}},
                {"kind": "final", "outcome": "success", "summary": "Searched."},
            ])
            engine = AgentEngine(root, model, PermissionPolicy([], [], []))
            engine.run("Find hits")
            result = next(e for e in engine.events if e["type"] == "tool_finished")["data"]["result"]
            self.assertEqual(len(result["matches"]), 100)
            self.assertTrue(result["truncated"])

    def test_replace_is_exact_backed_up_and_requires_fresh_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "module.py"
            source.write_text("value = 1\nvalue = 1\n", encoding="utf-8")
            check = ["/usr/bin/python3", "-m", "compileall", "-q", "."]
            model = ScriptedModel([
                {"kind": "plan", "steps": ["Edit", "Verify"]},
                {"kind": "tool", "name": "replace_text", "arguments": {
                    "path": "module.py", "old_text": "value = 1", "new_text": "value = 2",
                    "expected_replacements": 2,
                }},
                {"kind": "tool", "name": "run_command", "arguments": {"argv": check}},
                {"kind": "final", "outcome": "success", "summary": "Verified."},
            ])
            result = AgentEngine(
                root,
                model,
                PermissionPolicy(["module.py"], [check], [check]),
                command_runner=_PassingRunner(),
            ).run("Update values")

            self.assertEqual(result.status, "succeeded")
            self.assertEqual(source.read_text("utf-8"), "value = 2\nvalue = 2\n")
            backup = Path(result.state_file).parent / "backups" / "module.py"
            self.assertEqual(backup.read_text("utf-8"), "value = 1\nvalue = 1\n")
            self.assertEqual(result.changed_files, ["module.py"])

    def test_replace_rejects_wrong_occurrence_count_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "module.py"
            source.write_text("same\nsame\n", encoding="utf-8")
            model = ScriptedModel([
                {"kind": "plan", "steps": ["Edit"]},
                {"kind": "tool", "name": "replace_text", "arguments": {
                    "path": "module.py", "old_text": "same", "new_text": "new",
                    "expected_replacements": 1,
                }},
                {"kind": "final", "outcome": "failed", "summary": "Ambiguous edit."},
            ])
            result = AgentEngine(root, model, PermissionPolicy(["module.py"], [], [])).run("Edit once")
            self.assertEqual(result.status, "failed")
            self.assertEqual(source.read_text("utf-8"), "same\nsame\n")


if __name__ == "__main__":
    unittest.main()
