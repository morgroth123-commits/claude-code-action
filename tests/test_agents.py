from __future__ import annotations

import unittest

from chatmpd.agents import AgentCoordinator


class AgentCoordinatorTest(unittest.TestCase):
    def test_fans_out_independent_roles_and_consolidates_outputs(self) -> None:
        calls = []
        coordinator = AgentCoordinator(
            worker=lambda role, task: calls.append((role, task)) or f"{role}:{task}",
            consolidator=lambda outputs: " | ".join(sorted(outputs.values())),
            max_workers=3,
        )
        result = coordinator.run({
            "researcher": "find facts",
            "critic": "check risks",
            "verifier": "check result",
        })
        self.assertEqual(len(calls), 3)
        self.assertIn("researcher:find facts", result.summary)
        self.assertEqual(set(result.outputs), {"researcher", "critic", "verifier"})

    def test_rejects_unbounded_worker_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "max_workers"):
            AgentCoordinator(worker=lambda *_: None, max_workers=17)


if __name__ == "__main__":
    unittest.main()
