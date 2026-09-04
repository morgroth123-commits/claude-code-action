from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.model_registry import ModelRegistry, ModelRole
from chatmpd.model_runtime import ModelRuntimeManager


class _Runtime:
    endpoint = "http://127.0.0.1:8080"

    def __init__(self, model: Path) -> None:
        self.model = model
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1


class ModelRuntimeManagerTest(unittest.TestCase):
    def test_switches_models_by_role_and_reuses_active_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reasoner-20b.gguf").write_bytes(b"x")
            (root / "coder-7b.gguf").write_bytes(b"x")
            registry = ModelRegistry.discover([root])
            created: list[_Runtime] = []

            def factory(model: object) -> _Runtime:
                runtime = _Runtime(model.path)
                created.append(runtime)
                return runtime

            manager = ModelRuntimeManager(registry, runtime_factory=factory)
            first = manager.activate(ModelRole.REASONING)
            again = manager.activate(ModelRole.REASONING)
            coding = manager.activate(ModelRole.CODING)

            self.assertIs(first, again)
            self.assertEqual(first.starts, 2)
            self.assertEqual(first.stops, 1)
            self.assertEqual(coding.model.name, "coder-7b.gguf")
            self.assertEqual(len(created), 2)

    def test_falls_back_to_reasoning_when_requested_role_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reasoner-20b.gguf").write_bytes(b"x")
            registry = ModelRegistry.discover([root])
            manager = ModelRuntimeManager(
                registry,
                runtime_factory=lambda model: _Runtime(model.path),
            )

            runtime = manager.activate(ModelRole.CODING)

            self.assertEqual(runtime.model.name, "reasoner-20b.gguf")

    def test_stop_only_stops_the_active_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reasoner-20b.gguf").write_bytes(b"x")
            registry = ModelRegistry.discover([root])
            runtime = _Runtime(root / "reasoner-20b.gguf")
            manager = ModelRuntimeManager(
                registry,
                runtime_factory=lambda _model: runtime,
            )
            manager.activate(ModelRole.REASONING)

            manager.stop()
            manager.stop()

            self.assertEqual(runtime.stops, 1)


if __name__ == "__main__":
    unittest.main()
