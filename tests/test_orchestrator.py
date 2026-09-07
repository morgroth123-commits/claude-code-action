from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from chatmpd.orchestrator import ChatMPDOrchestrator, CommandResult


class _Assistant:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.conversation_id = "conv"

    def chat(self, text: str) -> object:
        self.calls.append(("chat", text))
        return SimpleNamespace(assistant=f"answer:{text}")

    def run_task(self, workspace: Path, text: str) -> object:
        self.calls.append(("coding", workspace, text))
        result = SimpleNamespace(
            status="succeeded", summary="fixed", changed_files=["a.py"],
            checks=[], state_file=workspace / ".chatmpd" / "run.json",
        )
        return SimpleNamespace(result=result, models=("coder",))

    def close(self) -> None:
        self.calls.append(("close",))


class OrchestratorTest(unittest.TestCase):
    def test_chat_and_coding_share_one_plain_language_front_door(self) -> None:
        assistant = _Assistant()
        orchestrator = ChatMPDOrchestrator(assistant=assistant)

        chat = orchestrator.command("Explain recursion")
        self.assertEqual(chat.capability, "chat")
        self.assertEqual(chat.message, "answer:Explain recursion")

        missing = orchestrator.command("Fix this code")
        self.assertEqual(missing.capability, "coding")
        self.assertEqual(missing.details["status"], "needs_context")
        self.assertEqual(missing.details["needs_context"]["kind"], "workspace")
        self.assertEqual(missing.details["suggested_action"], "choose_workspace")
        self.assertIn("project folder", missing.message.casefold())

        coded = orchestrator.command("Fix this code", workspace="C:/project")
        self.assertEqual(coded.capability, "coding")
        self.assertEqual(coded.message, "fixed")
        self.assertEqual(coded.details["changed_files"], ["a.py"])

    def test_specialist_handlers_are_routed_and_normalized(self) -> None:
        assistant = _Assistant()
        calls: list[str] = []
        orchestrator = ChatMPDOrchestrator(
            assistant=assistant,
            specialist_handlers={
                "eso": lambda text: calls.append("eso") or {"summary": "ESO healthy"},
                "vortex": lambda text: calls.append("vortex") or "3 profiles",
                "system": lambda text: calls.append("system") or {"summary": "Vader ready"},
                "media": lambda text: calls.append("media") or {"summary": "queued", "job_id": "1"},
            },
        )
        cases = (
            ("Scan ESO addons", "eso"),
            ("Inspect Vortex mod profiles", "vortex"),
            ("Check Windows system health", "system"),
            ("Generate an image of a castle", "media"),
        )
        for prompt, capability in cases:
            result = orchestrator.command(prompt)
            self.assertEqual(result.capability, capability)
            self.assertTrue(result.message)
        self.assertEqual(calls, ["eso", "vortex", "system", "media"])

    def test_command_result_is_mobile_json_ready_and_close_is_idempotent(self) -> None:
        assistant = _Assistant()
        orchestrator = ChatMPDOrchestrator(assistant=assistant)
        result = CommandResult("chat", "ok", {"path": Path("C:/x")})
        payload = result.as_dict()
        self.assertEqual(payload["capability"], "chat")
        self.assertEqual(payload["message"], "ok")
        self.assertEqual(payload["details"]["path"], "C:\\x")

        orchestrator.close()
        orchestrator.close()
        self.assertEqual(assistant.calls.count(("close",)), 1)


if __name__ == "__main__":
    unittest.main()


class OrchestratorToolEvidenceTest(unittest.TestCase):
    def test_chat_reports_visible_tool_names_without_raw_tool_payloads(self) -> None:
        assistant = _Assistant()
        assistant.chat = lambda text: SimpleNamespace(
            assistant="done", tools_used=("ext_plugin_echo",)
        )
        result = ChatMPDOrchestrator(assistant=assistant).command("Use echo")
        self.assertEqual(result.details["tools_used"], ["ext_plugin_echo"])


class AssistantFirstPlanningTest(unittest.TestCase):
    def test_injected_planner_routes_semantic_coding_without_keyword_dependency(self) -> None:
        from chatmpd.intent import IntentPlan

        class Planner:
            def __init__(self) -> None:
                self.calls = []

            def plan(self, text, *, workspace=None, capabilities=()):
                self.calls.append((text, workspace, tuple(capabilities)))
                return IntentPlan(
                    "coding", True, 0.96, "Project edit is requested."
                )

        assistant = _Assistant()
        planner = Planner()
        result = ChatMPDOrchestrator(
            assistant=assistant, intent_planner=planner
        ).command(
            "Make the calculator stop returning the wrong total",
            workspace="C:/project",
        )
        self.assertEqual(result.capability, "coding")
        self.assertEqual(assistant.calls[0][0], "coding")
        self.assertIn("coding", planner.calls[0][2])
        self.assertIn("chat", planner.calls[0][2])

    def test_malformed_planner_output_falls_back_to_deterministic_router(self) -> None:
        from chatmpd.intent import IntentPlanner

        class Provider:
            def chat(self, messages):
                return SimpleNamespace(text="not-json")

        assistant = _Assistant()
        result = ChatMPDOrchestrator(
            assistant=assistant, intent_planner=IntentPlanner(complete=lambda messages: Provider().chat(messages).text)
        ).command("Explain recursion")
        self.assertEqual(result.capability, "chat")
        self.assertEqual(assistant.calls[0], ("chat", "Explain recursion"))

    def test_low_confidence_plan_falls_back_to_router(self) -> None:
        from chatmpd.intent import IntentPlan

        class Planner:
            def plan(self, text, *, workspace=None, capabilities=()):
                return IntentPlan("coding", True, 0.1, "Weak guess")

        assistant = _Assistant()
        result = ChatMPDOrchestrator(
            assistant=assistant, intent_planner=Planner()
        ).command("Explain photosynthesis simply")
        self.assertEqual(result.capability, "chat")
