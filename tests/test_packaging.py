from __future__ import annotations

import ast
import unittest
from pathlib import Path


class PackagingDefinitionTest(unittest.TestCase):
    def test_windows_executable_is_one_file_named_chatmpd_without_a_console(self) -> None:
        root = Path(__file__).resolve().parents[1]
        spec_path = root / "ChatMPD.spec"
        tree = ast.parse(spec_path.read_text(encoding="utf-8"), filename=str(spec_path))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        analysis = next(
            call
            for call in calls
            if isinstance(call.func, ast.Name) and call.func.id == "Analysis"
        )
        executable = next(
            call
            for call in calls
            if isinstance(call.func, ast.Name) and call.func.id == "EXE"
        )
        scripts = ast.literal_eval(analysis.args[0])
        keywords = {keyword.arg: keyword.value for keyword in executable.keywords}

        self.assertEqual(scripts, ["chatmpd_launcher.py"])
        self.assertEqual(ast.literal_eval(keywords["name"]), "ChatMPD")
        self.assertIs(ast.literal_eval(keywords["console"]), False)
        self.assertIs(ast.literal_eval(keywords["upx"]), False)

        gitignore = (root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!ChatMPD.spec", gitignore.splitlines())

        launcher = (root / "chatmpd_launcher.py").read_text(encoding="utf-8")
        self.assertIn("from chatmpd.app import main", launcher)
        self.assertNotIn("from chatmpd.cli import main", launcher)


if __name__ == "__main__":
    unittest.main()
