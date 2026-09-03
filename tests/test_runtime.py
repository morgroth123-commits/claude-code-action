from __future__ import annotations

import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from chatmpd.runtime import (
    LlamaCppRuntime,
    RuntimeConfig,
    ServerProbe,
    discover_llama_server,
    discover_qwen_model,
    is_eso_running,
    probe_chatmpd_server,
)


class _FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.status = status
        self._body = BytesIO(payload)

    def read(self, _size: int = -1) -> bytes:
        return self._body.read(_size)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeOpener:
    def __init__(self, responses: dict[str, _FakeResponse]) -> None:
        self._responses = responses

    def open(self, request: object, timeout: float) -> _FakeResponse:
        del timeout
        return self._responses[getattr(request, "full_url")]


class _FakeProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid
        self.terminated = False
        self.killed = False

    def poll(self) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0

    def kill(self) -> None:
        self.killed = True


class _StubbornProcess(_FakeProcess):
    def wait(self, timeout: float | None = None) -> int:
        if not self.killed:
            raise subprocess.TimeoutExpired(cmd="llama-server.exe", timeout=timeout)
        return 0


class RuntimeDiscoveryTests(unittest.TestCase):
    def test_server_discovery_prefers_an_existing_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            server = Path(raw_tmp) / "llama-server.exe"
            server.touch()

            found = discover_llama_server(server, path_env="")

            self.assertEqual(found, server.resolve())


class RuntimeDiagnosticsTests(unittest.TestCase):
    def test_eso_detection_matches_the_exact_windows_process_name(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["tasklist"],
            returncode=0,
            stdout='"eso64.exe","8124","Console","1","1,024 K"\n',
            stderr="",
        )

        detected = is_eso_running(command_runner=lambda *_args, **_kwargs: completed)

        self.assertTrue(detected)

    def test_eso_detection_failure_uses_the_conservative_cpu_safe_mode(self) -> None:
        def unavailable(*_args: object, **_kwargs: object) -> object:
            raise OSError("tasklist unavailable")

        self.assertTrue(is_eso_running(command_runner=unavailable))

    def test_runtime_config_rejects_a_non_loopback_endpoint(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            RuntimeConfig(endpoint="http://0.0.0.0:8080")

    def test_runtime_config_rejects_unbounded_context_and_output(self) -> None:
        invalid = (
            ({"context_size": 0}, "context_size"),
            ({"context_size": 65_536}, "context_size"),
            ({"max_tokens": 0}, "max_tokens"),
            ({"max_tokens": 8_192}, "max_tokens"),
        )
        for overrides, message in invalid:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, message):
                    RuntimeConfig(**overrides)

    def test_diagnostics_report_missing_server_and_model_as_structured_issues(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            config = RuntimeConfig(
                server_path=root / "missing-server.exe",
                model_path=root / "missing-model.gguf",
                cache_root=root / "empty-cache",
                state_dir=root / "state",
            )
            runtime = LlamaCppRuntime(
                config,
                server_probe=lambda _endpoint, _timeout: ServerProbe(False, False, "offline"),
                eso_detector=lambda: False,
            )

            diagnostics = runtime.diagnose()

            self.assertIsNone(diagnostics.server_path)
            self.assertIsNone(diagnostics.model_path)
            self.assertFalse(diagnostics.endpoint_healthy)
            self.assertEqual(diagnostics.mode, "gpu-auto")
            self.assertEqual(
                diagnostics.issues,
                ("llama-server.exe was not found", "Qwen2.5-Coder-7B Q4_K_M model was not found"),
            )

    def test_probe_recognizes_a_healthy_server_with_the_chatmpd_alias(self) -> None:
        opener = _FakeOpener(
            {
                "http://127.0.0.1:8080/health": _FakeResponse(b'{"status":"ok"}'),
                "http://127.0.0.1:8080/v1/models": _FakeResponse(
                    b'{"object":"list","data":[{"id":"chatmpd-local","object":"model",'
                    b'"created":0,"owned_by":"local"}]}'
                ),
            }
        )

        probe = probe_chatmpd_server("http://127.0.0.1:8080", 0.5, opener=opener)

        self.assertEqual(probe, ServerProbe(True, True, "ready"))


class RuntimeLifecycleTests(unittest.TestCase):
    def test_runtime_can_be_constructed_with_safe_default_dependencies(self) -> None:
        runtime = LlamaCppRuntime(RuntimeConfig(endpoint="http://127.0.0.1:8099"))

        self.assertEqual(runtime.endpoint, "http://127.0.0.1:8099")

    def test_context_manager_starts_and_stops_only_its_owned_process(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            server = root / "llama-server.exe"
            model = root / "qwen.gguf"
            server.touch()
            model.touch()
            process = _FakeProcess(pid=9191)
            probes = iter(
                [ServerProbe(False, False, "offline"), ServerProbe(True, True, "ready")]
            )
            runtime = LlamaCppRuntime(
                RuntimeConfig(server_path=server, model_path=model, state_dir=root / "state"),
                server_probe=lambda _endpoint, _timeout: next(probes),
                eso_detector=lambda: False,
                process_launcher=lambda *_args, **_kwargs: process,
                sleeper=lambda _seconds: None,
            )

            with runtime as active:
                self.assertIs(active, runtime)
                self.assertEqual(active.endpoint, "http://127.0.0.1:8080")
                self.assertFalse(process.terminated)

            self.assertTrue(process.terminated)

    def test_start_refuses_an_existing_chatmpd_server_to_avoid_ownership_races(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            server = root / "llama-server.exe"
            model = root / "qwen.gguf"
            server.touch()
            model.touch()
            config = RuntimeConfig(
                server_path=server,
                model_path=model,
                state_dir=root / "state",
            )

            def must_not_launch(*_args: object, **_kwargs: object) -> object:
                raise AssertionError("an occupied endpoint must not be replaced")

            runtime = LlamaCppRuntime(
                config,
                server_probe=lambda _endpoint, _timeout: ServerProbe(True, True, "ready"),
                eso_detector=lambda: False,
                process_launcher=must_not_launch,
            )

            with self.assertRaisesRegex(RuntimeError, "already in use"):
                runtime.start()

    def test_start_refuses_to_replace_a_healthy_non_chatmpd_server(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            config = RuntimeConfig(state_dir=root / "state")

            def must_not_launch(*_args: object, **_kwargs: object) -> object:
                raise AssertionError("an occupied endpoint must not be replaced")

            runtime = LlamaCppRuntime(
                config,
                server_probe=lambda _endpoint, _timeout: ServerProbe(True, False, "unexpected server"),
                eso_detector=lambda: False,
                process_launcher=must_not_launch,
            )

            with self.assertRaisesRegex(RuntimeError, "non-ChatMPD"):
                runtime.start()

    def test_start_uses_cpu_safe_llamacpp_arguments_when_eso_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            server = root / "llama-server.exe"
            model = root / "model with spaces.gguf"
            server.touch()
            model.touch()
            config = RuntimeConfig(
                server_path=server,
                model_path=model,
                state_dir=root / "state",
            )
            probes = iter(
                [ServerProbe(False, False, "offline"), ServerProbe(True, True, "ready")]
            )
            launched: dict[str, object] = {}
            process = _FakeProcess()

            def launch(args: list[str], **kwargs: object) -> _FakeProcess:
                launched["args"] = args
                launched.update(kwargs)
                return process

            runtime = LlamaCppRuntime(
                config,
                server_probe=lambda _endpoint, _timeout: next(probes),
                eso_detector=lambda: True,
                process_launcher=launch,
                sleeper=lambda _seconds: None,
            )

            diagnostics = runtime.start()
            runtime.stop()

            args = launched["args"]
            self.assertIsInstance(args, list)
            self.assertEqual(args[0], str(server.resolve()))
            self.assertEqual(args[args.index("--model") + 1], str(model.resolve()))
            self.assertEqual(args[args.index("--host") + 1], "127.0.0.1")
            self.assertEqual(args[args.index("--port") + 1], "8080")
            self.assertEqual(args[args.index("--ctx-size") + 1], "8192")
            self.assertEqual(args[args.index("--n-predict") + 1], "512")
            self.assertEqual(args[args.index("--parallel") + 1], "1")
            self.assertEqual(args[args.index("--threads") + 1], "1")
            self.assertEqual(args[args.index("--threads-batch") + 1], "1")
            self.assertEqual(args[args.index("--n-gpu-layers") + 1], "0")
            self.assertIn("--no-webui", args)
            self.assertIn("--jinja", args)
            self.assertEqual(args[args.index("--cors-origins") + 1], "localhost")
            self.assertIn("--no-cors-credentials", args)
            self.assertNotIn("--api-key", args)
            self.assertNotIn("shell", launched)
            self.assertTrue(launched["creationflags"] & subprocess.CREATE_NO_WINDOW)
            self.assertTrue(launched["creationflags"] & subprocess.IDLE_PRIORITY_CLASS)
            self.assertEqual(diagnostics.mode, "cpu-safe")
            self.assertTrue(diagnostics.owned_server)
            self.assertEqual(diagnostics.pid, 4321)
            self.assertTrue(diagnostics.log_path.is_file())
            self.assertTrue(process.terminated)
            self.assertFalse(process.killed)

    def test_start_uses_gpu_auto_when_eso_is_not_running(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            server = root / "llama-server.exe"
            model = root / "qwen.gguf"
            server.touch()
            model.touch()
            probes = iter(
                [ServerProbe(False, False, "offline"), ServerProbe(True, True, "ready")]
            )
            launched: dict[str, object] = {}

            def launch(args: list[str], **kwargs: object) -> _FakeProcess:
                launched["args"] = args
                launched.update(kwargs)
                return _FakeProcess()

            runtime = LlamaCppRuntime(
                RuntimeConfig(server_path=server, model_path=model, state_dir=root / "state"),
                server_probe=lambda _endpoint, _timeout: next(probes),
                eso_detector=lambda: False,
                process_launcher=launch,
                sleeper=lambda _seconds: None,
            )

            diagnostics = runtime.start()
            runtime.stop()

            args = launched["args"]
            self.assertEqual(args[args.index("--n-gpu-layers") + 1], "auto")
            self.assertNotIn("--threads", args)
            self.assertEqual(diagnostics.mode, "gpu-auto")
            self.assertTrue(launched["creationflags"] & subprocess.CREATE_NO_WINDOW)
            self.assertFalse(launched["creationflags"] & subprocess.BELOW_NORMAL_PRIORITY_CLASS)

    def test_startup_timeout_stops_the_owned_process_and_keeps_its_log(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            server = root / "llama-server.exe"
            model = root / "qwen.gguf"
            server.touch()
            model.touch()
            process = _FakeProcess()
            clock = iter([10.0, 11.0])
            runtime = LlamaCppRuntime(
                RuntimeConfig(
                    server_path=server,
                    model_path=model,
                    state_dir=root / "state",
                    startup_timeout=0.5,
                ),
                server_probe=lambda _endpoint, _timeout: ServerProbe(False, False, "loading"),
                eso_detector=lambda: False,
                process_launcher=lambda *_args, **_kwargs: process,
                sleeper=lambda _seconds: None,
                monotonic=lambda: next(clock),
            )

            with self.assertRaisesRegex(RuntimeError, "startup timed out"):
                runtime.start()

            self.assertTrue(process.terminated)
            self.assertTrue((root / "state" / "llama-server.log").is_file())

    def test_launch_does_not_pass_api_keys_or_proxy_settings_to_server(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            server = root / "llama-server.exe"
            model = root / "qwen.gguf"
            server.touch()
            model.touch()
            probes = iter(
                [ServerProbe(False, False, "offline"), ServerProbe(True, True, "ready")]
            )
            launched: dict[str, object] = {}

            def launch(_args: list[str], **kwargs: object) -> _FakeProcess:
                launched.update(kwargs)
                return _FakeProcess()

            runtime = LlamaCppRuntime(
                RuntimeConfig(server_path=server, model_path=model, state_dir=root / "state"),
                server_probe=lambda _endpoint, _timeout: next(probes),
                eso_detector=lambda: False,
                process_launcher=launch,
                sleeper=lambda _seconds: None,
            )

            with patch.dict(
                "os.environ",
                {"OPENAI_API_KEY": "must-not-leak", "HTTPS_PROXY": "http://proxy.invalid"},
            ):
                runtime.start()
            runtime.stop()

            child_environment = launched["env"]
            self.assertNotIn("OPENAI_API_KEY", child_environment)
            self.assertNotIn("HTTPS_PROXY", child_environment)

    def test_stop_kills_an_owned_server_that_does_not_terminate(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            server = root / "llama-server.exe"
            model = root / "qwen.gguf"
            server.touch()
            model.touch()
            process = _StubbornProcess()
            probes = iter(
                [ServerProbe(False, False, "offline"), ServerProbe(True, True, "ready")]
            )
            runtime = LlamaCppRuntime(
                RuntimeConfig(server_path=server, model_path=model, state_dir=root / "state"),
                server_probe=lambda _endpoint, _timeout: next(probes),
                eso_detector=lambda: False,
                process_launcher=lambda *_args, **_kwargs: process,
                sleeper=lambda _seconds: None,
            )
            runtime.start()

            runtime.stop()

            self.assertTrue(process.terminated)
            self.assertTrue(process.killed)


class RuntimeCacheDiscoveryTests(unittest.TestCase):
    def test_model_discovery_prefers_an_existing_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            model = Path(raw_tmp) / "custom.gguf"
            model.touch()

            found = discover_qwen_model(model, cache_root=Path(raw_tmp) / "unused")

            self.assertEqual(found, model.resolve())

    def test_model_discovery_finds_the_official_qwen_coder_q4_k_m_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            cache = Path(raw_tmp)
            snapshot = cache / "hub" / "models--Qwen--Qwen2.5-Coder-7B-Instruct-GGUF" / "snapshots" / "abc"
            snapshot.mkdir(parents=True)
            model = snapshot / "qwen2.5-coder-7b-instruct-q4_k_m.gguf"
            model.touch()

            found = discover_qwen_model(cache_root=cache)

            self.assertEqual(found, model.resolve())

    def test_model_discovery_rejects_an_incomplete_split_download(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            cache = Path(raw_tmp)
            incomplete = cache / "qwen2.5-coder-7b-instruct-q4_k_m-00001-of-00002.gguf"
            incomplete.touch()

            found = discover_qwen_model(cache_root=cache)

            self.assertIsNone(found)

    def test_model_discovery_returns_the_first_shard_of_a_complete_split(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            cache = Path(raw_tmp)
            first = cache / "qwen2.5-coder-7b-instruct-q4_k_m-00001-of-00002.gguf"
            second = cache / "qwen2.5-coder-7b-instruct-q4_k_m-00002-of-00002.gguf"
            first.touch()
            second.touch()

            found = discover_qwen_model(cache_root=cache)

            self.assertEqual(found, first.resolve())

    def test_model_discovery_preserves_the_huggingface_snapshot_filename(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            cache = Path(raw_tmp)
            blob = cache / "blobs" / "content-hash"
            blob.parent.mkdir()
            blob.touch()
            snapshot = cache / "snapshots" / "qwen2.5-coder-7b-instruct-q4_k_m.gguf"
            snapshot.parent.mkdir()
            try:
                snapshot.symlink_to(blob)
            except OSError as exc:
                self.skipTest(f"file links are unavailable: {exc}")

            found = discover_qwen_model(cache_root=cache)

            self.assertEqual(found, snapshot.absolute())

    def test_server_discovery_uses_the_supplied_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            server = Path(raw_tmp) / "llama-server.exe"
            server.touch()

            found = discover_llama_server(path_env=raw_tmp, local_appdata=Path(raw_tmp) / "none")

            self.assertEqual(found, server.resolve())

    def test_server_discovery_falls_back_to_the_winget_llamacpp_package(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            local_appdata = Path(raw_tmp)
            package = (
                local_appdata
                / "Microsoft"
                / "WinGet"
                / "Packages"
                / "ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe"
            )
            package.mkdir(parents=True)
            server = package / "llama-server.exe"
            server.touch()

            found = discover_llama_server(path_env="", local_appdata=local_appdata)

            self.assertEqual(found, server.resolve())


if __name__ == "__main__":
    unittest.main()
