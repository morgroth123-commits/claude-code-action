from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.model_lab import ModelBenchmarkStore, ModelInventory
from chatmpd.model_registry import LocalModel, ModelRegistry, ModelRole
from chatmpd.platform_db import PlatformDatabase


class ModelLabTest(unittest.TestCase):
    def _registry(self) -> ModelRegistry:
        return ModelRegistry([
            LocalModel(Path("small.gguf"), "generic", (ModelRole.REASONING,), 3.0, 50),
            LocalModel(Path("large.gguf"), "generic", (ModelRole.REASONING,), 14.0, 50),
        ])

    def test_override_wins_and_benchmark_can_choose_best(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ModelBenchmarkStore(PlatformDatabase(Path(directory) / "db.sqlite"))
            store.record(ModelRole.REASONING, Path("small.gguf"), tokens_per_second=30, quality_score=0.65, memory_mb=2500)
            store.record(ModelRole.REASONING, Path("large.gguf"), tokens_per_second=10, quality_score=0.95, memory_mb=9000)
            inventory = ModelInventory(self._registry(), store)
            self.assertEqual(inventory.choose(ModelRole.REASONING).path, Path("large.gguf"))
            inventory.set_override(ModelRole.REASONING, Path("small.gguf"))
            self.assertEqual(inventory.choose(ModelRole.REASONING).path, Path("small.gguf"))

    def test_benchmarks_persist_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db.sqlite"
            first = ModelBenchmarkStore(PlatformDatabase(path))
            first.record(ModelRole.REASONING, Path("a.gguf"), tokens_per_second=12.5, quality_score=0.8, memory_mb=4000)
            second = ModelBenchmarkStore(PlatformDatabase(path))
            rows = second.list(ModelRole.REASONING)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].tokens_per_second, 12.5)
            self.assertEqual(rows[0].model_path, Path("a.gguf"))


if __name__ == "__main__":
    unittest.main()
