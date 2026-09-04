"""Plain-language prompt guidance for effective ChatMPD use."""

from __future__ import annotations

from typing import Iterable


_TEMPLATES = {
    "general": "Goal: <what you want>\nContext: <useful background>\nConstraints: <must/must not>\nDesired result: <deliverable>\nVerification: <how to know it worked>",
    "coding": "Goal: change <project behavior>\nContext: <repo/problem>\nConstraints: preserve <interfaces/data>\nDesired result: working code\nVerification: run the relevant tests and report evidence",
    "research": "Goal: answer <question>\nContext: <scope>\nConstraints: prioritize reliable sources\nDesired result: concise findings with sources\nVerification: distinguish confirmed facts from uncertainty",
    "system": "Goal: diagnose or change <PC behavior>\nContext: <symptoms>\nConstraints: do not weaken security or make critical changes without approval\nDesired result: stable verified state\nVerification: re-check the affected subsystem",
    "media": "Goal: create <image/video/audio>\nContext: <subject/style>\nConstraints: <format/duration/resolution>\nDesired result: saved local artifact\nVerification: confirm the file exists and inspect its metadata",
    "automation": "Goal: repeat or watch <task>\nContext: <when/why>\nConstraints: <frequency/condition>\nDesired result: local automation\nVerification: show next run and last result",
}


class PromptGuide:
    def templates(self) -> dict[str, str]:
        return dict(_TEMPLATES)

    def template(self, name: str) -> str:
        key = str(name).strip().casefold()
        if key not in _TEMPLATES:
            raise KeyError(f"Unknown prompt template: {name}")
        return _TEMPLATES[key]

    def optimize(
        self,
        goal: str,
        *,
        context: str = "",
        constraints: Iterable[str] = (),
        desired_result: str = "",
        verification: str = "",
    ) -> str:
        clean_goal = str(goal).strip()
        if not clean_goal:
            raise ValueError("Prompt goal cannot be blank.")
        constraint_lines = [str(item).strip() for item in constraints if str(item).strip()]
        sections = [
            ("Goal", clean_goal),
            ("Context", str(context).strip() or "Use the current conversation and local state."),
            ("Constraints", "\n".join(f"- {item}" for item in constraint_lines) or "- Preserve user data and existing safety boundaries."),
            ("Desired result", str(desired_result).strip() or "Complete the requested task and return the useful result."),
            ("Verification", str(verification).strip() or "Verify the result with the most relevant local checks and report evidence."),
        ]
        return "\n\n".join(f"## {heading}\n{text}" for heading, text in sections)
