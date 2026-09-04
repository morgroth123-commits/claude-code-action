from __future__ import annotations

import unittest
from typing import Any

from chatmpd.llamacpp import ChatResponse, ToolCall
from chatmpd.local_model import LocalCodingModel


class FakeProvider:
    def __init__(self, responses: list[ChatResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ChatResponse:
        self.requests.append(
            {"messages": messages, "tools": tools, "tool_choice": tool_choice}
        )
        return self.responses.pop(0)


class LocalCodingModelTest(unittest.TestCase):
    def test_green_check_does_not_auto_finish_a_task_that_still_requires_a_change(self) -> None:
        check = ["/usr/bin/python3", "-m", "compileall", "-q", "."]
        provider = FakeProvider(
            [
                ChatResponse("1. Inspect and repair", (), "stop"),
                ChatResponse(
                    "",
                    (ToolCall("check", "run_command", {"argv": check}),),
                    "tool_calls",
                ),
                ChatResponse("I still need to inspect the implementation.", (), "stop"),
            ]
        )
        model = LocalCodingModel(provider, allowed_commands=[check])
        model.next_turn(
            {"task": "Fix the implementation", "events": [{"type": "run_created"}]}
        )
        model.next_turn(
            {
                "task": "Fix the implementation",
                "events": [
                    {"type": "run_created"},
                    {"type": "model_turn"},
                    {"type": "plan_accepted"},
                ],
            }
        )

        turn = model.next_turn(
            {
                "task": "Fix the implementation",
                "events": [
                    {"type": "run_created"},
                    {"type": "model_turn"},
                    {"type": "plan_accepted"},
                    {
                        "sequence": 8,
                        "type": "tool_finished",
                        "data": {
                            "tool": "run_command",
                            "result": {"argv": check, "exit_code": 0},
                        },
                    },
                ],
            }
        )

        self.assertEqual(turn["kind"], "final")
        self.assertEqual(len(provider.requests), 3)

    def test_plans_routes_a_native_tool_and_returns_its_result_to_the_model(self) -> None:
        provider = FakeProvider(
            [
                ChatResponse(
                    "1. Inspect calculator.py\n2. Repair the defect\n3. Run tests",
                    (),
                    "stop",
                ),
                ChatResponse(
                    "I will inspect the implementation.",
                    (
                        ToolCall(
                            "call_read",
                            "read_file",
                            {"path": "calculator.py"},
                        ),
                    ),
                    "tool_calls",
                ),
                ChatResponse(
                    "SUCCESS: The implementation has been inspected and is correct.",
                    (),
                    "stop",
                ),
            ]
        )
        model = LocalCodingModel(
            provider,
            allowed_commands=[["python", "-m", "unittest"]],
            project_context="Git branch: main; working tree clean.",
        )

        plan = model.next_turn(
            {"task": "Inspect the calculator", "events": [{"type": "run_created"}]}
        )
        tool = model.next_turn(
            {
                "task": "Inspect the calculator",
                "events": [
                    {"type": "run_created"},
                    {"type": "model_turn"},
                    {"type": "plan_accepted"},
                ],
            }
        )
        final = model.next_turn(
            {
                "task": "Inspect the calculator",
                "events": [
                    {"type": "run_created"},
                    {"type": "model_turn"},
                    {"type": "plan_accepted"},
                    {"type": "model_turn"},
                    {"type": "tool_requested"},
                    {
                        "type": "tool_finished",
                        "data": {
                            "tool": "read_file",
                            "result": {
                                "path": "calculator.py",
                                "content": "answer = 42\n",
                            },
                        },
                    },
                ],
            }
        )

        self.assertEqual(
            plan,
            {
                "kind": "plan",
                "steps": [
                    "Inspect calculator.py",
                    "Repair the defect",
                    "Run tests",
                ],
            },
        )
        self.assertEqual(
            tool,
            {
                "kind": "tool",
                "name": "read_file",
                "arguments": {"path": "calculator.py"},
            },
        )
        self.assertEqual(final["kind"], "final")
        self.assertEqual(final["outcome"], "success")
        final_messages = provider.requests[-1]["messages"]
        tool_messages = [
            message for message in final_messages if message["role"] == "tool"
        ]
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages[0]["tool_call_id"], "call_read")
        self.assertIn("answer = 42", tool_messages[0]["content"])
        self.assertEqual(final_messages[-1]["role"], "user")
        self.assertIn("Continue executing", final_messages[-1]["content"])
        self.assertIn("exactly one provided tool", final_messages[-1]["content"])
        self.assertEqual(provider.requests[0]["tools"], None)
        self.assertIsNotNone(provider.requests[1]["tools"])
        self.assertEqual(provider.requests[1]["tool_choice"], "auto")
        self.assertEqual(provider.requests[1]["messages"][-1]["role"], "user")
        self.assertIn("Begin executing", provider.requests[1]["messages"][-1]["content"])

    def test_accepts_a_narrow_fenced_json_tool_fallback_from_a_local_model(self) -> None:
        provider = FakeProvider(
            [
                ChatResponse("1. Inspect the file", (), "stop"),
                ChatResponse(
                    '```json\n{"name":"read_file","arguments":{"path":"main.py"}}\n```',
                    (),
                    "stop",
                ),
            ]
        )
        model = LocalCodingModel(provider, allowed_commands=[])
        context = {"task": "Inspect main.py", "events": [{"type": "run_created"}]}
        model.next_turn(context)

        turn = model.next_turn(
            {
                "task": "Inspect main.py",
                "events": [
                    {"type": "run_created"},
                    {"type": "model_turn"},
                    {"type": "plan_accepted"},
                ],
            }
        )

        self.assertEqual(
            turn,
            {
                "kind": "tool",
                "name": "read_file",
                "arguments": {"path": "main.py"},
            },
        )

    def test_accepts_one_redundant_brace_pair_from_qwen_tool_fallback(self) -> None:
        provider = FakeProvider([
            ChatResponse("1. Inspect the project", (), "stop"),
            ChatResponse('{{"name":"list_files","arguments":{"path":"."}}}', (), "stop"),
        ])
        model = LocalCodingModel(provider, allowed_commands=[])
        model.next_turn({"task": "Inspect", "events": [{"type": "run_created"}]})
        turn = model.next_turn({
            "task": "Inspect",
            "events": [
                {"type": "run_created"},
                {"type": "model_turn"},
                {"type": "plan_accepted"},
            ],
        })
        self.assertEqual(turn, {
            "kind": "tool", "name": "list_files", "arguments": {"path": "."}
        })

    def test_allows_a_final_response_only_after_a_fresh_approved_check(self) -> None:
        check = ["/usr/bin/python3", "-m", "compileall", "-q", "."]
        provider = FakeProvider(
            [
                ChatResponse("1. Verify", (), "stop"),
                ChatResponse(
                    "",
                    (ToolCall("check", "run_command", {"argv": check}),),
                    "tool_calls",
                ),
                ChatResponse("SUCCESS: Verified successfully.", (), "stop"),
            ]
        )
        model = LocalCodingModel(provider, allowed_commands=[check])
        model.next_turn(
            {"task": "Verify", "events": [{"sequence": 1, "type": "run_created"}]}
        )
        model.next_turn(
            {
                "task": "Verify",
                "events": [
                    {"sequence": 1, "type": "run_created"},
                    {"sequence": 2, "type": "model_turn"},
                    {"sequence": 3, "type": "plan_accepted"},
                ],
            }
        )

        final = model.next_turn(
            {
                "task": "Verify",
                "events": [
                    {"sequence": 1, "type": "run_created"},
                    {"sequence": 2, "type": "model_turn"},
                    {"sequence": 3, "type": "plan_accepted"},
                    {
                        "sequence": 8,
                        "type": "tool_finished",
                        "data": {
                            "tool": "run_command",
                            "result": {"argv": check, "exit_code": 0},
                        },
                    },
                ],
            }
        )

        self.assertEqual(final["kind"], "final")
        self.assertEqual(final["outcome"], "success")
        self.assertEqual(final["summary"], "Verified successfully.")
        self.assertEqual(provider.requests[1]["tool_choice"], "auto")
        self.assertEqual(len(provider.requests), 3)
        final_prompt = provider.requests[2]["messages"][-1]
        self.assertEqual(final_prompt["role"], "user")
        self.assertIn("checks have passed", final_prompt["content"].casefold())
        self.assertIn("final summary", final_prompt["content"].casefold())

    def test_ambiguous_final_text_fails_closed_instead_of_claiming_success(self) -> None:
        provider = FakeProvider(
            [
                ChatResponse("1. Inspect", (), "stop"),
                ChatResponse("I could not complete or verify the repair.", (), "stop"),
            ]
        )
        model = LocalCodingModel(provider, allowed_commands=[])
        model.next_turn(
            {"task": "Inspect the project", "events": [{"type": "run_created"}]}
        )

        turn = model.next_turn(
            {
                "task": "Inspect the project",
                "events": [
                    {"type": "run_created"},
                    {"type": "model_turn"},
                    {"type": "plan_accepted"},
                ],
            }
        )

        self.assertEqual(turn["kind"], "final")
        self.assertEqual(turn["outcome"], "failed")
        self.assertIn("could not complete", turn["summary"])


if __name__ == "__main__":
    unittest.main()
