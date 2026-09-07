from __future__ import annotations

import json
import unittest

from chatmpd.intent import IntentPlanner


class _Completer:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.calls = []

    def __call__(self, messages) -> str:
        self.calls.append(messages)
        if isinstance(self.payload, str):
            return self.payload
        return json.dumps(self.payload)


class IntentPlannerTest(unittest.TestCase):
    def test_rejects_blank_prompt_before_calling_provider(self) -> None:
        completer = _Completer({
            "capability": "chat", "requires_workspace": False, "confidence": 1,
        })
        planner = IntentPlanner(complete=completer)
        with self.assertRaisesRegex(ValueError, "Describe"):
            planner.plan("   ", capabilities=("chat",))
        self.assertEqual(completer.calls, [])

    def test_rejects_unknown_capability_from_provider(self) -> None:
        planner = IntentPlanner(complete=_Completer({
            "capability": "teleport", "requires_workspace": False,
            "confidence": 0.9, "reason": "requested",
        }))
        with self.assertRaisesRegex(ValueError, "capability"):
            planner.plan("Do something", capabilities=("chat", "coding"))

    def test_clamps_numeric_confidence_and_preserves_safe_context_fields(self) -> None:
        planner = IntentPlanner(complete=_Completer({
            "capability": "coding",
            "requires_workspace": True,
            "confidence": 1.7,
            "reason": "Needs project edits",
            "missing_context": "workspace",
            "suggested_action": "choose_workspace",
        }))
        plan = planner.plan(
            "Make the calculator stop returning the wrong total",
            capabilities=("chat", "coding"),
        )
        self.assertEqual(plan.capability, "coding")
        self.assertEqual(plan.confidence, 1.0)
        self.assertTrue(plan.requires_workspace)
        self.assertEqual(plan.missing_context, "workspace")
        self.assertEqual(plan.suggested_action, "choose_workspace")

    def test_rejects_unknown_schema_fields(self) -> None:
        planner = IntentPlanner(complete=_Completer({
            "capability": "chat", "requires_workspace": False,
            "confidence": 0.9, "invented_tool": "shell",
        }))
        with self.assertRaisesRegex(ValueError, "field"):
            planner.plan("Explain this", capabilities=("chat",))

    def test_requires_workspace_must_be_boolean(self) -> None:
        planner = IntentPlanner(complete=_Completer({
            "capability": "chat",
            "requires_workspace": "false",
            "confidence": 0.9,
        }))
        with self.assertRaisesRegex(ValueError, "requires_workspace"):
            planner.plan("Explain this", capabilities=("chat",))


if __name__ == "__main__":
    unittest.main()
