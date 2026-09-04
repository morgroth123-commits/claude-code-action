from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.model_registry import ModelRegistry, ModelRole


class ModelRegistryTest(unittest.TestCase):
    def test_discovers_role_specific_local_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in (
                "reasoner-20b.gguf",
                "coder-7b.gguf",
                "fast-1.5b.gguf",
                "embed-v2.gguf",
            ):
                (root / name).write_bytes(b"x")
            registry = ModelRegistry.discover([root])
            self.assertIsNotNone(registry.best(ModelRole.REASONING))
            self.assertIsNotNone(registry.best(ModelRole.CODING))
            self.assertIsNotNone(registry.best(ModelRole.FAST))
            self.assertIsNotNone(registry.best(ModelRole.EMBEDDING))


class SplitModelRegistryTest(unittest.TestCase):
    def test_complete_split_gguf_is_registered_once_using_first_shard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "qwen2.5-coder-7b-q4_k_m-00001-of-00002.gguf"
            second = root / "qwen2.5-coder-7b-q4_k_m-00002-of-00002.gguf"
            first.write_bytes(b"a")
            second.write_bytes(b"b")

            registry = ModelRegistry.discover([root])
            coding = registry.for_role(ModelRole.CODING)

            self.assertEqual(len(coding), 1)
            self.assertEqual(coding[0].path.resolve(), first.resolve())

    def test_incomplete_split_gguf_is_not_registered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "coder-7b-00001-of-00002.gguf").write_bytes(b"a")
            registry = ModelRegistry.discover([root])
            self.assertEqual(registry.for_role(ModelRole.CODING), ())
