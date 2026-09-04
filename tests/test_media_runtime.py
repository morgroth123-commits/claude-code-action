from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.media_runtime import (
    ComfyUIServerProbe,
    MediaRuntimeConfig,
    MediaRuntime,
)


class _FakeProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid
        self.terminated = False
        self.killed = False

    def poll(self):
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True


class MediaRuntimeTest(unittest.TestCase):
    def _portable_tree(self, root: Path) -> None:
        python = root / "python_embeded" / "python.exe"
        main = root / "ComfyUI" / "main.py"
        python.parent.mkdir(parents=True)
        main.parent.mkdir(parents=True)
        python.write_bytes(b"")
        main.write_text("# comfy", encoding="utf-8")

    def test_rejects_non_loopback_endpoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            MediaRuntimeConfig(endpoint="http://192.168.1.20:8188")

    def test_attaches_to_existing_local_server_without_spawning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._portable_tree(root)
            runtime = MediaRuntime(
                MediaRuntimeConfig(root=root),
                server_probe=lambda endpoint, timeout: ComfyUIServerProbe(True, "ready"),
                eso_detector=lambda: False,
                process_launcher=lambda *args, **kwargs: self.fail("must not spawn"),
            )
            diagnostics = runtime.start()
            self.assertTrue(diagnostics.endpoint_healthy)
            self.assertFalse(diagnostics.owned_server)

    def test_refuses_to_start_gpu_media_while_eso_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._portable_tree(root)
            runtime = MediaRuntime(
                MediaRuntimeConfig(root=root),
                server_probe=lambda endpoint, timeout: ComfyUIServerProbe(False, "stopped"),
                eso_detector=lambda: True,
                process_launcher=lambda *args, **kwargs: self.fail("must not spawn"),
            )
            with self.assertRaisesRegex(RuntimeError, "ESO"):
                runtime.start()

    def test_launches_hidden_server_with_shared_storage_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "portable"
            shared = base / "shared"
            self._portable_tree(root)
            for name in ("models", "input", "output", "user"):
                (shared / name).mkdir(parents=True)
            calls = []
            process = _FakeProcess()
            probes = iter([
                ComfyUIServerProbe(False, "stopped"),
                ComfyUIServerProbe(True, "ready"),
            ])
            def launch(command, **options):
                calls.append((command, options))
                return process

            runtime = MediaRuntime(
                MediaRuntimeConfig(
                    root=root,
                    models_dir=shared / "models",
                    input_dir=shared / "input",
                    output_dir=shared / "output",
                    user_dir=shared / "user",
                    state_dir=base / "state",
                    startup_timeout=5,
                    poll_interval=0,
                ),
                server_probe=lambda endpoint, timeout: next(probes),
                eso_detector=lambda: False,
                process_launcher=launch,
                sleeper=lambda _: None,
            )
            diagnostics = runtime.start()
            self.assertTrue(diagnostics.owned_server)
            command = [str(part) for part in calls[0][0]]
            self.assertIn("--disable-auto-launch", command)
            self.assertIn("--models-directory", command)
            self.assertIn(str(shared / "models"), command)
            self.assertIn("127.0.0.1", command)
            self.assertIn("USERNAME", calls[0][1]["env"])
            runtime.stop()
            self.assertTrue(process.terminated)


if __name__ == "__main__":
    unittest.main()


class MediaDesktopLayoutTest(unittest.TestCase):
    def test_diagnose_accepts_comfy_desktop_managed_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / "ComfyUI" / ".venv" / "Scripts" / "python.exe"
            main = root / "ComfyUI" / "main.py"
            python.parent.mkdir(parents=True)
            main.parent.mkdir(parents=True, exist_ok=True)
            python.write_bytes(b"")
            main.write_text("# comfy", encoding="utf-8")
            runtime = MediaRuntime(
                MediaRuntimeConfig(root=root),
                server_probe=lambda endpoint, timeout: ComfyUIServerProbe(False, "stopped"),
                eso_detector=lambda: False,
            )
            diagnostics = runtime.diagnose()
            self.assertEqual(diagnostics.python_path, python)
            self.assertEqual(diagnostics.main_path, main)
            self.assertEqual(diagnostics.issues, ())
