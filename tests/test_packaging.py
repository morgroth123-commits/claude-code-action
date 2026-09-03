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

    def test_build_copies_the_usage_guide_beside_the_executable(self) -> None:
        root = Path(__file__).resolve().parents[1]
        guide = (root / "docs" / "most-effective-usage.md").read_text(
            encoding="utf-8"
        )
        build = (root / "scripts" / "build-windows.ps1").read_text(
            encoding="utf-8"
        )
        readme = (root / "README.md").read_text(encoding="utf-8")

        self.assertIn("# Most Effective Use of ChatMPD", guide)
        self.assertIn("Ctrl+Enter", guide)
        self.assertIn("Never put passwords", guide)
        self.assertIn("Most Effective Usage.md", build)
        self.assertIn("docs/most-effective-usage.md", readme)

    def test_runtime_keeps_zero_required_third_party_dependencies(self) -> None:
        root = Path(__file__).resolve().parents[1]
        project = (root / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn("dependencies = []", project)


if __name__ == "__main__":
    unittest.main()
