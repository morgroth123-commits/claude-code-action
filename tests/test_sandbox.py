from __future__ import annotations

import json
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path, PureWindowsPath

from chatmpd.sandbox import SandboxRunner


class SandboxRunnerIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = SandboxRunner()
        cls.health = cls.runner.probe()

    def setUp(self) -> None:
        if not self.health.available:
            self.skipTest(self.health.detail)

    def test_preserves_argv_without_shell_expansion(self) -> None:
        # Break caught: interpolating guest arguments into a shell command.
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            literal_arguments = [
                "space value",
                "$(touch /work/pwned)",
                "semi;colon",
                "*.py",
                '"quoted"',
                "back\\slash",
            ]
            program = (
                "import json, pathlib, sys; "
                "print(json.dumps(sys.argv[1:])); "
                "print(pathlib.Path('/work/pwned').exists())"
            )

            result = self.runner.run(
                workspace,
                ["/usr/bin/python3", "-c", program, *literal_arguments],
                timeout_seconds=5,
            )

            self.assertEqual(result.status, "completed", result.stderr)
            self.assertEqual(result.exit_code, 0, result.stderr)
            output_lines = result.stdout.splitlines()
            self.assertEqual(json.loads(output_lines[0]), literal_arguments)
            self.assertEqual(output_lines[1], "False")

    def test_hides_windows_filesystem_and_disables_network(self) -> None:
        # Break caught: mounting /mnt or omitting the network namespace.
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            sentinel = workspace / "host-only.txt"
            sentinel.write_text("must stay on Windows", encoding="utf-8")
            guest_host_path = self._wsl_automount_path(sentinel)
            program = (
                "import json, pathlib, socket, sys; "
                "sock = socket.socket(); sock.settimeout(0.5); "
                "code = sock.connect_ex(('1.1.1.1', 53)); "
                "print(json.dumps({'host_exists': pathlib.Path(sys.argv[1]).exists(), "
                "'network_code': code}))"
            )

            result = self.runner.run(
                workspace,
                ["/usr/bin/python3", "-c", program, guest_host_path],
                timeout_seconds=5,
            )

            self.assertEqual(result.status, "completed", result.stderr)
            observation = json.loads(result.stdout)
            self.assertFalse(observation["host_exists"])
            self.assertNotEqual(observation["network_code"], 0)

    def test_guest_writes_do_not_change_host_workspace(self) -> None:
        # Break caught: bind-mounting the real workspace writable at /work.
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            source = workspace / "value.txt"
            source.write_text("host original", encoding="utf-8")
            program = (
                "from pathlib import Path; "
                "path = Path('value.txt'); path.write_text('guest edit'); "
                "print(path.read_text())"
            )

            result = self.runner.run(
                workspace,
                ["/usr/bin/python3", "-c", program],
                timeout_seconds=5,
            )

            self.assertEqual(result.status, "completed", result.stderr)
            self.assertEqual(result.stdout.strip(), "guest edit")
            self.assertEqual(source.read_text(encoding="utf-8"), "host original")

    def test_runs_a_legitimate_python_test_from_snapshot(self) -> None:
        # Break caught: failing to transfer or execute an ordinary project tree.
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "tests").mkdir()
            (workspace / "calculator.py").write_text(
                "def add(left, right):\n    return left + right\n",
                encoding="utf-8",
            )
            (workspace / "tests" / "test_calculator.py").write_text(
                "import unittest\n"
                "from calculator import add\n\n"
                "class CalculatorTest(unittest.TestCase):\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(20, 22), 42)\n",
                encoding="utf-8",
            )

            result = self.runner.run(
                workspace,
                [
                    "/usr/bin/python3",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                ],
                timeout_seconds=10,
            )

            self.assertEqual(result.status, "completed", result.stderr)
            self.assertEqual(result.exit_code, 0, result.stderr)
            self.assertIn("OK", result.stdout + result.stderr)
            self.assertGreaterEqual(result.snapshot_files, 2)

    def test_excludes_repository_metadata_secrets_and_caches(self) -> None:
        # Break caught: copying credentials or disposable caches into the guest.
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            hidden_paths = [
                workspace / ".git" / "config",
                workspace / ".chatmpd" / "runs" / "state.json",
                workspace / "secrets" / "token.txt",
                workspace / "__pycache__" / "module.pyc",
                workspace / ".env",
            ]
            for path in hidden_paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("sensitive", encoding="utf-8")
            (workspace / "visible.py").write_text("print('visible')\n", encoding="utf-8")
            program = (
                "import json; from pathlib import Path; "
                "print(json.dumps({name: Path(name).exists() for name in "
                "['.git', '.chatmpd', 'secrets', '__pycache__', '.env', 'visible.py']}))"
            )

            result = self.runner.run(
                workspace,
                ["/usr/bin/python3", "-c", program],
                timeout_seconds=5,
            )

            self.assertEqual(result.status, "completed", result.stderr)
            observed = json.loads(result.stdout)
            self.assertEqual(
                observed,
                {
                    ".git": False,
                    ".chatmpd": False,
                    "secrets": False,
                    "__pycache__": False,
                    ".env": False,
                    "visible.py": True,
                },
            )

    def test_bounds_combined_output(self) -> None:
        # Break caught: collecting unbounded child output in host memory.
        with tempfile.TemporaryDirectory() as temporary_directory:
            program = (
                "import sys; "
                "sys.stdout.write('o' * 200000); sys.stdout.flush(); "
                "sys.stderr.write('e' * 200000); sys.stderr.flush()"
            )

            result = self.runner.run(
                Path(temporary_directory),
                ["/usr/bin/python3", "-c", program],
                timeout_seconds=5,
                output_limit_bytes=4096,
            )

            captured_bytes = len(result.stdout.encode()) + len(result.stderr.encode())
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.exit_code, 0)
            self.assertLessEqual(captured_bytes, 4096)
            self.assertTrue(result.output_truncated)

    def test_timeout_is_bounded_and_kills_descendants(self) -> None:
        # Break caught: killing only wsl.exe while a sandbox descendant survives.
        with tempfile.TemporaryDirectory() as temporary_directory:
            token = f"chatmpd-timeout-{uuid.uuid4().hex}"
            child = "import time; time.sleep(30)"
            program = (
                "import subprocess, sys, time; "
                "subprocess.Popen(['/usr/bin/python3', '-c', sys.argv[1], sys.argv[2]], "
                "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
                "stderr=subprocess.DEVNULL, start_new_session=True); "
                "time.sleep(30)"
            )
            started = time.monotonic()

            result = self.runner.run(
                Path(temporary_directory),
                ["/usr/bin/python3", "-c", program, child, token],
                timeout_seconds=0.5,
            )

            elapsed = time.monotonic() - started
            self.assertEqual(result.status, "timed_out", result.stderr)
            self.assertTrue(result.timed_out)
            self.assertLess(elapsed, 8)
            lingering = subprocess.run(
                [
                    "wsl.exe",
                    "-d",
                    "Ubuntu",
                    "--",
                    "/usr/bin/pgrep",
                    "-f",
                    token,
                ],
                capture_output=True,
                text=True,
                timeout=5,
                shell=False,
                check=False,
            )
            self.assertEqual(lingering.returncode, 1, lingering.stdout)

    @staticmethod
    def _wsl_automount_path(path: Path) -> str:
        windows_path = PureWindowsPath(path.resolve())
        drive = windows_path.drive.rstrip(":").lower()
        tail = "/".join(windows_path.parts[1:])
        return f"/mnt/{drive}/{tail}"


class SandboxAvailabilityTest(unittest.TestCase):
    def test_missing_wsl_returns_structured_unavailable_result(self) -> None:
        # Break caught: leaking FileNotFoundError when WSL is absent or unhealthy.
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing = Path(temporary_directory) / "missing-wsl.exe"
            runner = SandboxRunner(wsl_executable=str(missing))

            result = runner.run(
                Path(temporary_directory),
                ["/usr/bin/true"],
                timeout_seconds=1,
            )

            self.assertEqual(result.status, "unavailable")
            self.assertIsNone(result.exit_code)
            self.assertFalse(result.timed_out)
            self.assertIn("WSL", result.error or "")


if __name__ == "__main__":
    unittest.main()
