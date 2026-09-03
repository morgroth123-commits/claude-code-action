"""High-level ChatMPD project task orchestration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .engine import AgentEngine, RunResult
from .llamacpp import LlamaCppProvider
from .local_model import LocalCodingModel
from .policy import PermissionPolicy
from .project import ProjectProfile, profile_project
from .sandbox import SandboxRunner


class UnsupportedProjectError(RuntimeError):
    """Raised when ChatMPD cannot identify a safe offline verification gate."""


@dataclass(frozen=True)
class TaskOutcome:
    profile: ProjectProfile
    result: RunResult
    models: tuple[str, ...]


@dataclass(frozen=True)
class PreparedTask:
    root: Path
    task: str
    profile: ProjectProfile
    command_runner: Any


def prepare_project_task(
    workspace: Path,
    task: str,
    *,
    command_runner: Any | None = None,
) -> PreparedTask:
    """Validate a task and its isolated verifier before loading the model."""

    root = Path(workspace).resolve(strict=True)
    cleaned_task = str(task).strip()
    if not cleaned_task:
        raise ValueError("A coding task is required")
    if len(cleaned_task.encode("utf-8")) > 32_768:
        raise ValueError("The coding task exceeds the 32 KiB limit")

    profile = profile_project(root)
    if not profile.supported or not profile.required_checks:
        raise UnsupportedProjectError(profile.detail)

    isolated_runner = command_runner or SandboxRunner()
    probe = getattr(isolated_runner, "probe", None)
    if callable(probe):
        health = probe()
        if not health.available:
            raise RuntimeError(
                f"Isolated verification is unavailable: {health.detail}"
            )
    return PreparedTask(root, cleaned_task, profile, isolated_runner)


def run_project_task(
    workspace: Path,
    task: str,
    *,
    endpoint: str = "http://127.0.0.1:8080",
    provider: Any | None = None,
    command_runner: Any | None = None,
    prepared: PreparedTask | None = None,
) -> TaskOutcome:
    task_setup = prepared or prepare_project_task(
        workspace, task, command_runner=command_runner
    )
    root = Path(workspace).resolve(strict=True)
    cleaned_task = str(task).strip()
    if root != task_setup.root or cleaned_task != task_setup.task:
        raise ValueError("Prepared task does not match the requested workspace and task")
    profile = task_setup.profile
    isolated_runner = task_setup.command_runner

    local_provider = provider or LlamaCppProvider(endpoint=endpoint, timeout=120)
    if not local_provider.health():
        raise RuntimeError("The local ChatMPD model is not ready")
    models = tuple(local_provider.models())
    if not models:
        raise RuntimeError("The local ChatMPD server did not advertise a model")

    model = LocalCodingModel(
        local_provider,
        allowed_commands=profile.verification_commands,
        project_context=_project_context(profile),
    )
    policy = PermissionPolicy(
        writable_paths=["**"],
        allowed_commands=[list(command) for command in profile.verification_commands],
        required_checks=[list(command) for command in profile.required_checks],
    )
    engine = AgentEngine(
        root,
        model,
        policy,
        command_runner=isolated_runner,
    )
    result = engine.run(cleaned_task)
    return TaskOutcome(profile, result, models)


def _project_context(profile: ProjectProfile) -> str:
    payload = {
        "project_type": profile.project_type,
        "detail": profile.detail,
        "manifest": [asdict(entry) for entry in profile.manifest],
        "manifest_truncated": profile.manifest_truncated,
        "git": asdict(profile.git),
        "approved_verification_commands": profile.verification_commands,
    }
    return json.dumps(payload, ensure_ascii=True, sort_keys=True)
