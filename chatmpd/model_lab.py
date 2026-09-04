"""Persistent local model evaluation, inventory, and role overrides."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .model_registry import LocalModel, ModelRegistry, ModelRole
from .platform_db import PlatformDatabase


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class ModelBenchmark:
    role: ModelRole
    model_path: Path
    tokens_per_second: float
    quality_score: float
    memory_mb: int
    created_at: str

    @property
    def score(self) -> float:
        speed = min(max(self.tokens_per_second, 0.0) / 50.0, 1.0)
        quality = min(max(self.quality_score, 0.0), 1.0)
        return quality * 0.75 + speed * 0.25


class ModelBenchmarkStore:
    def __init__(self, database: PlatformDatabase | None = None) -> None:
        self.database = database or PlatformDatabase()

    def record(
        self,
        role: ModelRole,
        model_path: Path,
        *,
        tokens_per_second: float,
        quality_score: float,
        memory_mb: int,
    ) -> ModelBenchmark:
        benchmark = ModelBenchmark(
            ModelRole(role), Path(model_path), float(tokens_per_second),
            float(quality_score), int(memory_mb), _now(),
        )
        payload = json.dumps({
            "role": benchmark.role.value,
            "model_path": str(benchmark.model_path),
            "tokens_per_second": benchmark.tokens_per_second,
            "quality_score": benchmark.quality_score,
            "memory_mb": benchmark.memory_mb,
            "created_at": benchmark.created_at,
        })
        record_id = f"{benchmark.role.value}:{benchmark.model_path}"
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO platform_records VALUES (?, ?, ?, ?)",
                ("model-benchmark", record_id, payload, benchmark.created_at),
            )
            connection.commit()
        return benchmark

    def list(self, role: ModelRole | None = None) -> tuple[ModelBenchmark, ...]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? ORDER BY updated_at DESC",
                ("model-benchmark",),
            ).fetchall()
        results: list[ModelBenchmark] = []
        for row in rows:
            item = json.loads(str(row["payload"]))
            parsed_role = ModelRole(item["role"])
            if role is not None and parsed_role != ModelRole(role):
                continue
            results.append(ModelBenchmark(
                parsed_role, Path(item["model_path"]),
                float(item["tokens_per_second"]), float(item["quality_score"]),
                int(item["memory_mb"]), str(item["created_at"]),
            ))
        return tuple(results)

    def set_override(self, role: ModelRole, model_path: Path | None) -> None:
        with self.database.connect() as connection:
            if model_path is None:
                connection.execute(
                    "DELETE FROM platform_records WHERE namespace=? AND record_id=?",
                    ("model-override", ModelRole(role).value),
                )
            else:
                payload = json.dumps({"model_path": str(Path(model_path))})
                connection.execute(
                    "INSERT OR REPLACE INTO platform_records VALUES (?, ?, ?, ?)",
                    ("model-override", ModelRole(role).value, payload, _now()),
                )
            connection.commit()

    def get_override(self, role: ModelRole) -> Path | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? AND record_id=?",
                ("model-override", ModelRole(role).value),
            ).fetchone()
        if row is None:
            return None
        item = json.loads(str(row["payload"]))
        return Path(str(item["model_path"]))


class ModelInventory:
    def __init__(
        self,
        registry: ModelRegistry,
        benchmark_store: ModelBenchmarkStore | None = None,
    ) -> None:
        self.registry = registry
        self.benchmarks = benchmark_store or ModelBenchmarkStore()

    def set_override(self, role: ModelRole, model_path: Path | None) -> None:
        self.benchmarks.set_override(role, model_path)

    def choose(self, role: ModelRole) -> LocalModel | None:
        role = ModelRole(role)
        candidates = self.registry.for_role(role)
        override = self.benchmarks.get_override(role)
        if override is not None:
            for model in candidates:
                if model.path == override or model.path.name == override.name:
                    return model
        ranked = {item.model_path.name: item for item in self.benchmarks.list(role)}
        benchmarked = [model for model in candidates if model.path.name in ranked]
        if benchmarked:
            benchmarked.sort(key=lambda model: ranked[model.path.name].score, reverse=True)
            return benchmarked[0]
        return self.registry.best(role)
