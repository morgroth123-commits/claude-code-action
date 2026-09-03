from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from chatmpd.project import profile_project


class ProjectProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.workspace = Path(self.temporary_directory.name)

    def _git(self, *arguments: str) -> None:
        subprocess.run(
            ["git", *arguments],
            cwd=self.workspace,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
            check=True,
        )

    def test_python_unittest_project_uses_the_offline_sandbox_interpreter(self) -> None:
        # Break caught: falling back to a host command, shell string, or installer.
        tests = self.workspace / "tests"
        tests.mkdir()
        (tests / "test_calculator.py").write_text(
            "import unittest\n\n"
            "class CalculatorTest(unittest.TestCase):\n"
            "    def test_value(self):\n"
            "        self.assertEqual(6 * 7, 42)\n",
            encoding="utf-8",
        )

        profile = profile_project(self.workspace)

        expected = [
            ["/usr/bin/python3", "-m", "unittest", "discover", "-s", "tests"]
        ]
        self.assertTrue(profile.supported)
        self.assertEqual("python-unittest", profile.project_type)
        self.assertEqual(expected, profile.verification_commands)
        self.assertEqual(expected, profile.required_checks)
        self.assertTrue(all(isinstance(command, list) for command in expected))

    def test_single_file_python_project_falls_back_to_syntax_verification(self) -> None:
        # Break caught: treating a testless Python project as unsupported or executing it.
        (self.workspace / "application.py").write_text(
            "def answer():\n    return 42\n",
            encoding="utf-8",
        )

        profile = profile_project(self.workspace)

        expected = [["/usr/bin/python3", "-m", "compileall", "-q", "."]]
        self.assertTrue(profile.supported)
        self.assertEqual("python-syntax", profile.project_type)
        self.assertEqual(expected, profile.verification_commands)
        self.assertEqual(expected, profile.required_checks)

    def test_pytest_only_project_falls_back_to_syntax_verification(self) -> None:
        # Break caught: sending pytest functions through unittest discovery.
        tests = self.workspace / "tests"
        tests.mkdir()
        (tests / "test_calculator.py").write_text(
            "def test_value():\n"
            "    assert 6 * 7 == 42\n",
            encoding="utf-8",
        )

        profile = profile_project(self.workspace)

        expected = [["/usr/bin/python3", "-m", "compileall", "-q", "."]]
        self.assertTrue(profile.supported)
        self.assertEqual("python-syntax", profile.project_type)
        self.assertEqual("Python project with syntax verification", profile.detail)
        self.assertEqual(expected, profile.verification_commands)
        self.assertEqual(expected, profile.required_checks)

    def test_test_named_python_without_tests_falls_back_to_syntax_verification(self) -> None:
        # Break caught: treating an arbitrary test-named Python file as unittest-based.
        tests = self.workspace / "tests"
        tests.mkdir()
        (tests / "test_data.py").write_text(
            "EXAMPLE_DATA = {'answer': 42}\n",
            encoding="utf-8",
        )

        profile = profile_project(self.workspace)

        expected = [["/usr/bin/python3", "-m", "compileall", "-q", "."]]
        self.assertTrue(profile.supported)
        self.assertEqual("python-syntax", profile.project_type)
        self.assertEqual("Python project with syntax verification", profile.detail)
        self.assertEqual(expected, profile.verification_commands)
        self.assertEqual(expected, profile.required_checks)

    def test_manifest_excludes_secrets_internal_state_caches_and_links(self) -> None:
        # Break caught: sending credentials or out-of-tree/reparse content to the model.
        (self.workspace / "application.py").write_text("value = 42\n", encoding="utf-8")
        (self.workspace / "README.md").write_text("safe\n", encoding="utf-8")
        (self.workspace / ".env.example").write_text("TOKEN=\n", encoding="utf-8")
        hidden_files = [
            self.workspace / ".env",
            self.workspace / ".npmrc",
            self.workspace / "private.pem",
            self.workspace / ".git" / "config",
            self.workspace / ".chatmpd" / "runs" / "state.json",
            self.workspace / "__pycache__" / "application.pyc",
            self.workspace / ".pytest_cache" / "cache.json",
            self.workspace / "secrets" / "token.txt",
        ]
        for hidden_file in hidden_files:
            hidden_file.parent.mkdir(parents=True, exist_ok=True)
            hidden_file.write_text("never expose this\n", encoding="utf-8")

        linked = self.workspace / "linked.py"
        try:
            linked.symlink_to(self.workspace / "secrets" / "token.txt")
        except OSError:
            linked = None

        profile = profile_project(self.workspace)

        paths = {entry.path for entry in profile.manifest}
        self.assertEqual({".env.example", "application.py", "README.md"}, paths)
        if linked is not None:
            self.assertNotIn("linked.py", paths)
        self.assertFalse(profile.manifest_truncated)

    def test_manifest_is_deterministic_and_bounded(self) -> None:
        # Break caught: allowing a very large tree to create unbounded model context.
        for index in range(6):
            (self.workspace / f"file-{index}.txt").write_text(
                f"file {index}\n",
                encoding="utf-8",
            )

        profile = profile_project(self.workspace, max_inventory_files=3)

        self.assertEqual(
            ["file-0.txt", "file-1.txt", "file-2.txt"],
            [entry.path for entry in profile.manifest],
        )
        self.assertTrue(profile.manifest_truncated)

    def test_manifest_stops_traversal_after_the_first_overflow_file(self) -> None:
        # Break caught: walking the rest of a large tree after the manifest is bounded.
        (self.workspace / "a.txt").write_text("first\n", encoding="utf-8")
        (self.workspace / "b.txt").write_text("overflow\n", encoding="utf-8")
        unvisited = self.workspace / "z-unvisited"
        unvisited.mkdir()
        (unvisited / "late.txt").write_text("must not be scanned\n", encoding="utf-8")
        real_scandir = os.scandir
        visited: list[Path] = []

        def tracking_scandir(directory: os.PathLike[str] | str):
            visited.append(Path(directory).resolve())
            return real_scandir(directory)

        with patch("chatmpd.project.os.scandir", side_effect=tracking_scandir):
            profile = profile_project(self.workspace, max_inventory_files=1)

        self.assertEqual(["a.txt"], [entry.path for entry in profile.manifest])
        self.assertTrue(profile.manifest_truncated)
        self.assertNotIn(unvisited.resolve(), visited)

    def test_git_context_is_collected_and_sensitive_paths_are_redacted(self) -> None:
        # Break caught: leaking origin credentials or tracked secret-file changes.
        self._git("init", "-b", "main")
        (self.workspace / "application.py").write_text("value = 1\n", encoding="utf-8")
        (self.workspace / "README.md").write_text("before\n", encoding="utf-8")
        (self.workspace / ".env").write_text("TOP_SECRET=before\n", encoding="utf-8")
        self._git("add", "application.py", "README.md", ".env")
        self._git(
            "-c",
            "user.name=ChatMPD Tests",
            "-c",
            "user.email=chatmpd@example.invalid",
            "commit",
            "-m",
            "initial",
        )
        self._git(
            "remote",
            "add",
            "origin",
            "https://alice:credential@github.com/example-owner/example-repo.git",
        )
        (self.workspace / "README.md").write_text("after\n", encoding="utf-8")
        (self.workspace / ".env").write_text("TOP_SECRET=after\n", encoding="utf-8")

        profile = profile_project(self.workspace)

        self.assertTrue(profile.git.is_repository)
        self.assertEqual("main", profile.git.branch)
        self.assertEqual("example-owner/example-repo", profile.git.origin)
        self.assertTrue(profile.git.dirty)
        self.assertIn("README.md", profile.git.status)
        self.assertIn("+after", profile.git.diff)
        serialized = json.dumps(asdict(profile.git))
        self.assertNotIn("alice", serialized)
        self.assertNotIn("credential", serialized)
        self.assertNotIn("TOP_SECRET", serialized)
        self.assertNotIn(".env", serialized)

    def test_unknown_project_returns_no_safe_check_without_installing_anything(self) -> None:
        # Break caught: inventing a package install, network call, or unsafe generic command.
        (self.workspace / "package.json").write_text(
            '{"name":"unknown-project"}\n',
            encoding="utf-8",
        )
        (self.workspace / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

        profile = profile_project(self.workspace)

        self.assertFalse(profile.supported)
        self.assertEqual("unsupported", profile.project_type)
        self.assertEqual(
            "Unsupported project: no safe offline verification command was identified.",
            profile.detail,
        )
        self.assertEqual([], profile.verification_commands)
        self.assertEqual([], profile.required_checks)


if __name__ == "__main__":
    unittest.main()
