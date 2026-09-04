from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.model_registry import ModelRegistry, ModelRole
from chatmpd.model_runtime import ModelRuntimeManager


class _Runtime:
    endpoint = "http://127.0.0.1:8080"
    def __init__(self, model): self.model = model
    def start(self): pass
    def stop(self): pass


class ModelRuntimeSelectorTest(unittest.TestCase):
    def test_external_selector_can_override_registry_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reasoner-20b.gguf").write_bytes(b"x")
            (root / "reasoner-7b.gguf").write_bytes(b"x")
            registry = ModelRegistry.discover([root])
            smaller = next(model for model in registry.models if model.path.name == "reasoner-7b.gguf")
            manager = ModelRuntimeManager(
                registry,
                runtime_factory=lambda model: _Runtime(model),
                selector=lambda role: smaller if role == ModelRole.REASONING else None,
            )
            runtime = manager.activate(ModelRole.REASONING)
            self.assertEqual(runtime.model.path.name, "reasoner-7b.gguf")
