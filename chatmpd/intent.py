"""Schema-validated assistant-first intent planning for ChatMPD."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .router import RequestRouter, RouteDecision


DEFAULT_CAPABILITIES: tuple[str, ...] = (
    "chat",
    "coding",
    "system",
    "performance",
    "eso",
    "vortex",
    "media",
)

_PLANNER_SYSTEM = """You are ChatMPD's intent planner. Choose exactly one capability for the user's request.
Reply with one JSON object only. No markdown. No commentary.
Allowed capabilities: {capabilities}
Schema:
{{"capability":"<one allowed>","requires_workspace":true|false,"confidence":0.0-1.0,"reason":"short user-safe text","missing_context":null|"short need","suggested_action":null|"choose_workspace"}}
Rules:
- Never invent capabilities or tools.
- coding requires_workspace true when the user wants project edits/fixes/builds/tests.
- If a project folder is required but not provided, set missing_context and suggested_action to choose_workspace.
- Prefer chat for ordinary questions and explanations.
- Keep reason free of model names, tool ids, and backend jargon.
"""


CompleteFn = Callable[[list[dict[str, str]]], str]


@dataclass(frozen=True)
class IntentPlan:
    capability: str
    requires_workspace: bool = False
    confidence: float = 1.0
    reason: str = ""
    missing_context: str | None = None
    suggested_action: str | None = None

    def to_route_decision(self) -> RouteDecision:
        return RouteDecision(
            capability=self.capability,
            requires_workspace=self.requires_workspace,
            reason=self.reason,
        )


def _clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("confidence must be a number") from error
    if number != number:  # NaN
        raise ValueError("confidence must be finite")
    return max(0.0, min(1.0, number))


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    return text[:240] or None


def parse_intent_plan(
    payload: Any,
    *,
    capabilities: Sequence[str] = DEFAULT_CAPABILITIES,
) -> IntentPlan:
    """Validate planner output against the supported capability catalog."""

    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("planner output is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("planner output must be a JSON object")

    allowed = {str(item).strip() for item in capabilities if str(item).strip()}
    if not allowed:
        raise ValueError("capability catalog is empty")

    unknown = set(payload) - {
        "capability",
        "requires_workspace",
        "confidence",
        "reason",
        "missing_context",
        "suggested_action",
    }
    if unknown:
        raise ValueError(f"planner output has unknown fields: {sorted(unknown)}")

    capability = str(payload.get("capability", "")).strip()
    if capability not in allowed:
        raise ValueError(f"unknown capability: {capability or '(empty)'}")

    raw_requires_workspace = payload.get("requires_workspace", False)
    if not isinstance(raw_requires_workspace, bool):
        raise ValueError("requires_workspace must be a boolean")
    requires_workspace = raw_requires_workspace
    confidence = _clamp_confidence(payload.get("confidence", 1.0))
    reason = " ".join(str(payload.get("reason", "")).split()).strip()[:240]
    missing_context = _clean_optional_text(payload.get("missing_context"))
    suggested_action = _clean_optional_text(payload.get("suggested_action"))
    if suggested_action is not None and len(suggested_action) > 64:
        suggested_action = suggested_action[:64]

    if capability == "coding":
        requires_workspace = True

    return IntentPlan(
        capability=capability,
        requires_workspace=requires_workspace,
        confidence=confidence,
        reason=reason,
        missing_context=missing_context,
        suggested_action=suggested_action,
    )


class IntentPlanner:
    """Produce a bounded IntentPlan from ordinary language, without inventing tools."""

    def __init__(
        self,
        *,
        complete: CompleteFn | None = None,
        capabilities: Sequence[str] = DEFAULT_CAPABILITIES,
        confidence_threshold: float = 0.55,
        fallback_router: RequestRouter | None = None,
    ) -> None:
        catalog = tuple(dict.fromkeys(str(item).strip() for item in capabilities if str(item).strip()))
        if not catalog:
            raise ValueError("capabilities must include at least one route")
        self.capabilities = catalog
        self.complete = complete
        self.confidence_threshold = _clamp_confidence(confidence_threshold)
        self.fallback_router = fallback_router or RequestRouter()

    def plan(
        self,
        text: str,
        *,
        workspace: str | None = None,
        capabilities: Sequence[str] | None = None,
    ) -> IntentPlan:
        prompt = str(text).strip()
        if not prompt:
            raise ValueError("Describe what you want ChatMPD to do.")
        catalog = tuple(capabilities) if capabilities is not None else self.capabilities
        if not catalog:
            raise ValueError("capability catalog is empty")

        if self.complete is not None:
            try:
                messages = [
                    {
                        "role": "system",
                        "content": _PLANNER_SYSTEM.format(
                            capabilities=", ".join(catalog)
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "request": prompt,
                                "workspace_selected": bool(
                                    workspace and str(workspace).strip()
                                ),
                                "capabilities": list(catalog),
                            },
                            ensure_ascii=True,
                        ),
                    },
                ]
                raw = self.complete(messages)
                plan = parse_intent_plan(raw, capabilities=catalog)
                if plan.confidence < self.confidence_threshold:
                    raise ValueError("planner confidence below threshold")
                return self._apply_workspace_context(plan, workspace)
            except Exception:
                # Provider, JSON, schema, or confidence failure → caller may fall back.
                raise

        # Without a model completer, use deterministic router as a structured plan.
        decision = self.fallback_router.classify(prompt)
        capability = decision.capability if decision.capability in catalog else "chat"
        plan = IntentPlan(
            capability=capability,
            requires_workspace=bool(decision.requires_workspace) or capability == "coding",
            confidence=0.7 if capability != "chat" else 0.6,
            reason=decision.reason or "Deterministic route selected.",
        )
        return self._apply_workspace_context(plan, workspace)

    @staticmethod
    def _apply_workspace_context(
        plan: IntentPlan, workspace: str | None
    ) -> IntentPlan:
        if not plan.requires_workspace:
            return plan
        if workspace and str(workspace).strip():
            return plan
        return IntentPlan(
            capability=plan.capability,
            requires_workspace=True,
            confidence=plan.confidence,
            reason=plan.reason or "A project folder is required.",
            missing_context=plan.missing_context
            or "Choose the project folder you want ChatMPD to work in.",
            suggested_action=plan.suggested_action or "choose_workspace",
        )
