"""Bounded coordinator for temporary ChatMPD specialist roles."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Mapping


Worker = Callable[[str, str], str]
Consolidator = Callable[[Mapping[str, str]], str]


@dataclass(frozen=True)
class AgentRunResult:
    summary: str
    outputs: dict[str, str]


class AgentCoordinator:
    """Run independent specialist roles and consolidate their visible results."""

    def __init__(
        self,
        *,
        worker: Worker,
        consolidator: Consolidator | None = None,
        max_workers: int = 4,
    ) -> None:
        if not 1 <= int(max_workers) <= 16:
            raise ValueError("max_workers must be between 1 and 16")
        self.worker = worker
        self.consolidator = consolidator or self._default_consolidator
        self.max_workers = int(max_workers)

    def run(self, assignments: Mapping[str, str]) -> AgentRunResult:
        tasks = {str(role).strip(): str(task).strip() for role, task in assignments.items()}
        tasks = {role: task for role, task in tasks.items() if role and task}
        if not tasks:
            raise ValueError("At least one specialist assignment is required.")
        if len(tasks) > self.max_workers:
            raise ValueError("Assignment count exceeds max_workers.")

        outputs: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks))) as executor:
            futures = {
                executor.submit(self.worker, role, task): role
                for role, task in tasks.items()
            }
            for future in as_completed(futures):
                role = futures[future]
                outputs[role] = str(future.result())
        return AgentRunResult(
            summary=str(self.consolidator(outputs)),
            outputs=outputs,
        )

    @staticmethod
    def _default_consolidator(outputs: Mapping[str, str]) -> str:
        return "\n\n".join(
            f"{role}: {text}" for role, text in sorted(outputs.items())
        )
