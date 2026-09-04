"""Discovery and role selection for local ChatMPD model assets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable


class ModelRole(str, Enum):
    REASONING = "reasoning"
    CODING = "coding"
    FAST = "fast"
    EMBEDDING = "embedding"


@dataclass(frozen=True)
class LocalModel:
    path: Path
    family: str
    roles: tuple[ModelRole, ...]
    parameter_billions: float | None
    priority: int

    @property
    def name(self) -> str:
        return self.path.name


def _size_from_name(name: str) -> float | None:
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)b(?!\w)", name.casefold())
    return float(match.group(1)) if match else None


def _describe(path: Path) -> LocalModel:
    name = path.name.casefold()
    size = _size_from_name(name)
    if "nomic" in name or "embed" in name:
        return LocalModel(path, "nomic", (ModelRole.EMBEDDING,), size, 100)
    if "gpt-oss" in name or "reasoner" in name or "reasoning" in name:
        roles = (ModelRole.REASONING,)
        if size is not None and size <= 3:
            roles += (ModelRole.FAST,)
        return LocalModel(path, "gpt-oss", roles, size, 100)
    if "coder" in name:
        roles = (ModelRole.CODING,)
        if size is not None and size <= 3:
            roles += (ModelRole.FAST,)
        return LocalModel(path, "qwen-coder", roles, size, 95)
    if "fast" in name or (size is not None and size <= 3):
        return LocalModel(path, "generic", (ModelRole.FAST,), size, 70)
    return LocalModel(path, "generic", (ModelRole.REASONING,), size, 50)


class ModelRegistry:
    """Inventory locally available GGUF models and select them by role."""

    def __init__(self, models: Iterable[LocalModel]) -> None:
        self.models = tuple(models)

    @classmethod
    def discover(cls, roots: Iterable[Path]) -> "ModelRegistry":
        found: list[LocalModel] = []
        seen: set[Path] = set()
        for root in roots:
            candidate_root = Path(root).expanduser()
            if not candidate_root.exists():
                continue
            for path in candidate_root.rglob("*.gguf"):
                split = re.match(
                    r"^(.*)-(\d{5})-of-(\d{5})(\.gguf)$",
                    path.name,
                    flags=re.IGNORECASE,
                )
                if split is not None:
                    prefix, raw_part, raw_total, suffix = split.groups()
                    if int(raw_part) != 1:
                        continue
                    total = int(raw_total)
                    if not all(
                        (path.parent / f"{prefix}-{part:05d}-of-{total:05d}{suffix}").is_file()
                        for part in range(1, total + 1)
                    ):
                        continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                found.append(_describe(path))
        return cls(found)

    def for_role(self, role: ModelRole) -> tuple[LocalModel, ...]:
        matches = [model for model in self.models if role in model.roles]
        return tuple(sorted(matches, key=self._score, reverse=True))

    def best(self, role: ModelRole) -> LocalModel | None:
        matches = self.for_role(role)
        return matches[0] if matches else None

    @staticmethod
    def _score(model: LocalModel) -> tuple[int, float, str]:
        size = model.parameter_billions or 0.0
        return model.priority, size, model.name.casefold()
