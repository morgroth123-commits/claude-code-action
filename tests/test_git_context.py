from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from chatmpd import git_context
from chatmpd.git_context import collect_git_context


class GitContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)

    def _git(self, repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=repository,
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
            check=True,
        )

    def _create_repository(self, name: str = "repository") -> Path:
        repository = self.directory / name
        repository.mkdir()
        self._git(repository, "init", "-b", "main")
        (repository / "README.md").write_text("before\n", encoding="utf-8")
        self._git(repository, "add", "README.md")
        self._git(
            repository,
            "-c",
            "user.name=ChatMPD Tests",
            "-c",
            "user.email=chatmpd@example.invalid",
            "commit",
            "-m",
            "initial",
        )
        return repository

    def test_returns_non_repository_context_for_an_ordinary_directory(self) -> None:
        context = collect_git_context(self.directory)

        self.assertFalse(context.is_repository)
        self.assertIsNone(context.root)
        self.assertIsNone(context.branch)
        self.assertFalse(context.dirty)
        self.assertIsNone(context.origin_owner)
        self.assertIsNone(context.origin_repo)
        self.assertEqual("", context.status)
        self.assertEqual("", context.diff)
        self.assertEqual("not a git repository", context.error)

    def test_reports_dirty_repository_without_leaking_origin_credentials(self) -> None:
        repository = self._create_repository("repo & still-safe")
        self._git(
            repository,
            "remote",
            "add",
            "origin",
            "https://alice:super-secret@github.com/example-owner/example-repo.git",
        )
        (repository / "README.md").write_text("after\n", encoding="utf-8")
        (repository / "new.py").write_text("value = 1\n", encoding="utf-8")

        context = collect_git_context(repository / ".git" / "..")

        self.assertTrue(context.is_repository)
        self.assertEqual(str(repository.resolve()), context.root)
        self.assertEqual("main", context.branch)
        self.assertTrue(context.dirty)
        self.assertEqual("example-owner", context.origin_owner)
        self.assertEqual("example-repo", context.origin_repo)
        self.assertIn(" M README.md", context.status)
        self.assertIn("?? new.py", context.status)
        self.assertIn("+after", context.diff)
        serialized = json.dumps(asdict(context))
        self.assertNotIn("alice", serialized)
        self.assertNotIn("super-secret", serialized)

    def test_reports_a_clean_repository(self) -> None:
        repository = self._create_repository()

        context = collect_git_context(repository)

        self.assertTrue(context.is_repository)
        self.assertFalse(context.dirty)
        self.assertEqual("", context.status)
        self.assertEqual("", context.diff)
        self.assertIsNone(context.error)

    def test_diff_includes_staged_changes(self) -> None:
        repository = self._create_repository()
        (repository / "README.md").write_text("staged change\n", encoding="utf-8")
        self._git(repository, "add", "README.md")

        context = collect_git_context(repository)

        self.assertTrue(context.dirty)
        self.assertIn("M  README.md", context.status)
        self.assertIn("+staged change", context.diff)

    def test_subdirectory_context_excludes_sibling_paths_and_content(self) -> None:
        # Break caught: collecting repository-wide changes for a selected subdirectory.
        repository = self._create_repository()
        selected = repository / "selected[1]"
        sibling = repository / "sibling"
        selected.mkdir()
        sibling.mkdir()
        (selected / "staged.py").write_text("value = 'before staged'\n", encoding="utf-8")
        (selected / "unstaged.py").write_text("value = 'before unstaged'\n", encoding="utf-8")
        (sibling / "private.py").write_text("value = 'before sibling'\n", encoding="utf-8")
        self._git(repository, "add", "--all")
        self._git(
            repository,
            "-c",
            "user.name=ChatMPD Tests",
            "-c",
            "user.email=chatmpd@example.invalid",
            "commit",
            "-m",
            "add scoped fixtures",
        )
        self._git(
            repository,
            "remote",
            "add",
            "origin",
            "https://credential@example.invalid/example-owner/example-repo.git",
        )
        (selected / "staged.py").write_text(
            "value = 'selected staged marker'\n",
            encoding="utf-8",
        )
        (sibling / "private.py").write_text(
            "value = 'sibling staged secret'\n",
            encoding="utf-8",
        )
        self._git(repository, "add", "--all")
        (selected / "unstaged.py").write_text(
            "value = 'selected unstaged marker'\n",
            encoding="utf-8",
        )
        (sibling / "private.py").write_text(
            "value = 'sibling unstaged secret'\n",
            encoding="utf-8",
        )

        context = collect_git_context(selected)

        self.assertTrue(context.is_repository)
        self.assertEqual(str(repository.resolve()), context.root)
        self.assertEqual("main", context.branch)
        self.assertEqual("example-owner", context.origin_owner)
        self.assertEqual("example-repo", context.origin_repo)
        self.assertTrue(context.dirty)
        self.assertIn("selected[1]/staged.py", context.status)
        self.assertIn("selected[1]/unstaged.py", context.status)
        self.assertIn("selected staged marker", context.diff)
        self.assertIn("selected unstaged marker", context.diff)
        self.assertNotIn("sibling", context.status)
        self.assertNotIn("sibling", context.diff)
        self.assertNotIn("sibling staged secret", context.diff)
        self.assertNotIn("sibling unstaged secret", context.diff)

    def test_repository_root_context_includes_changes_from_all_subdirectories(self) -> None:
        # Break caught: accidentally applying subdirectory scoping to a root selection.
        repository = self._create_repository()
        nested = repository / "nested"
        nested.mkdir()
        tracked = nested / "tracked.py"
        tracked.write_text("value = 'before'\n", encoding="utf-8")
        self._git(repository, "add", "--all")
        self._git(
            repository,
            "-c",
            "user.name=ChatMPD Tests",
            "-c",
            "user.email=chatmpd@example.invalid",
            "commit",
            "-m",
            "add nested fixture",
        )
        tracked.write_text("value = 'root selection marker'\n", encoding="utf-8")

        context = collect_git_context(repository)

        self.assertIn("nested/tracked.py", context.status)
        self.assertIn("root selection marker", context.diff)

    def test_git_runner_suppresses_windows_and_never_uses_a_shell(self) -> None:
        # Break caught: a Git child process flashing a terminal window over the game.
        invocations: list[dict[str, object]] = []

        def fake_run(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            invocations.append(kwargs)
            return subprocess.CompletedProcess([], 0)

        with patch("chatmpd.git_context.subprocess.run", side_effect=fake_run):
            result = git_context._run_git(
                self.directory,
                ["status", "--porcelain=v1"],
                sys.executable,
                1.0,
                1_024,
            )

        expected_creation_flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        )
        self.assertIsNotNone(result)
        self.assertEqual(1, len(invocations))
        self.assertEqual(expected_creation_flags, invocations[0].get("creationflags"))
        self.assertIs(False, invocations[0].get("shell"))

    def test_limits_large_diff_output(self) -> None:
        repository = self._create_repository()
        large_file = repository / "large.txt"
        large_file.write_text("original\n", encoding="utf-8")
        self._git(repository, "add", "large.txt")
        self._git(
            repository,
            "-c",
            "user.name=ChatMPD Tests",
            "-c",
            "user.email=chatmpd@example.invalid",
            "commit",
            "-m",
            "add large file",
        )
        large_file.write_text("".join(f"changed {index}\n" for index in range(500)), encoding="utf-8")

        context = collect_git_context(repository, output_limit=180)

        self.assertLessEqual(len(context.diff.encode("utf-8")), 180)
        self.assertIn("[truncated]", context.diff)

    def test_does_not_execute_a_repository_text_conversion_program(self) -> None:
        repository = self._create_repository()
        binary_file = repository / "sample.bin"
        attributes = repository / ".gitattributes"
        binary_file.write_bytes(b"before\x00")
        attributes.write_text("*.bin diff=unsafe\n", encoding="utf-8")
        self._git(repository, "add", "sample.bin", ".gitattributes")
        self._git(
            repository,
            "-c",
            "user.name=ChatMPD Tests",
            "-c",
            "user.email=chatmpd@example.invalid",
            "commit",
            "-m",
            "add binary fixture",
        )
        converter = repository / "converter.py"
        marker = repository / "converter-ran.txt"
        converter.write_text(
            "import pathlib, sys\n"
            "pathlib.Path(sys.argv[1]).write_text('ran', encoding='utf-8')\n"
            "print(pathlib.Path(sys.argv[2]).read_bytes())\n",
            encoding="utf-8",
        )
        command = " ".join(
            f'"{Path(value).as_posix()}"'
            for value in (sys.executable, converter, marker)
        )
        self._git(repository, "config", "diff.unsafe.textconv", command)
        binary_file.write_bytes(b"after\x00")

        collect_git_context(repository)

        self.assertFalse(marker.exists())

    def test_does_not_execute_a_repository_filesystem_monitor_hook(self) -> None:
        repository = self._create_repository()
        hook = repository / ".git" / "hooks" / "chatmpd-fsmonitor"
        marker = repository / "fsmonitor-ran.txt"
        hook.write_text(
            "#!/bin/sh\n"
            "printf ran > fsmonitor-ran.txt\n"
            "exit 1\n",
            encoding="utf-8",
            newline="\n",
        )
        hook.chmod(0o755)
        self._git(repository, "config", "core.fsmonitor", hook.as_posix())

        collect_git_context(repository)

        self.assertFalse(marker.exists())

    @unittest.skipUnless(os.name == "nt", "Windows executable search regression")
    def test_ignores_a_fake_git_executable_in_the_process_directory(self) -> None:
        repository = self._create_repository()
        shutil.copy2(sys.executable, repository / "git.exe")
        previous_directory = Path.cwd()
        self.addCleanup(os.chdir, previous_directory)
        os.chdir(repository)

        context = collect_git_context(repository)

        self.assertTrue(context.is_repository)
        self.assertEqual(str(repository.resolve()), context.root)


if __name__ == "__main__":
    unittest.main()
