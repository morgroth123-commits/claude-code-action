"""Role-aware lifecycle management for local ChatMPD models."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .model_registry import LocalModel, ModelRegistry, ModelRole


RuntimeFactory = Callable[[LocalModel], Any]


class ModelRuntimeManager:
    """Keep at most one role-selected local model runtime active."""

    def __init__(
        self,
        registry: ModelRegistry,
        *,
        runtime_factory: RuntimeFactory,
        selector: Callable[[ModelRole], LocalModel | None] | None = None,
    ) -> None:
        self.registry = registry
        self._runtime_factory = runtime_factory
        self._selector = selector
        self._active_model: LocalModel | None = None
        self._active_runtime: Any | None = None

    @property
    def active_model(self) -> LocalModel | None:
        return self._active_model

    @property
    def endpoint(self) -> str:
        if self._active_runtime is None:
            raise RuntimeError("No local model runtime is active")
        return str(self._active_runtime.endpoint)

    def activate(self, role: ModelRole) -> Any:
        model = self._select(role)
        if self._active_model == model and self._active_runtime is not None:
            self._active_runtime.start()
            return self._active_runtime

        self.stop()
        runtime = self._runtime_factory(model)
        try:
            runtime.start()
        except BaseException:
            try:
                runtime.stop()
            finally:
                raise
        self._active_model = model
        self._active_runtime = runtime
        return runtime

    def stop(self) -> None:
        runtime = self._active_runtime
        self._active_runtime = None
        self._active_model = None
        if runtime is not None:
            runtime.stop()

    def _select(self, role: ModelRole) -> LocalModel:
        model = self._selector(role) if self._selector is not None else None
        if model is not None:
            return model
        model = self.registry.best(role)
        if model is not None:
            return model

        fallback_order = {
            ModelRole.CODING: (ModelRole.REASONING, ModelRole.FAST),
            ModelRole.REASONING: (ModelRole.CODING, ModelRole.FAST),
            ModelRole.FAST: (ModelRole.REASONING, ModelRole.CODING),
            ModelRole.EMBEDDING: (),
        }[role]
        for fallback in fallback_order:
            model = self.registry.best(fallback)
            if model is not None:
                return model
        raise RuntimeError(f"No local model is available for role: {role.value}")
