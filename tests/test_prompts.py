from __future__ import annotations

import unittest

from chatmpd.prompts import PromptGuide


class PromptGuideTest(unittest.TestCase):
    def test_optimizer_uses_goal_context_constraints_result_verification(self) -> None:
        guide = PromptGuide()
        optimized = guide.optimize(
            "fix my addon issue",
            context="ESO stutters after enabling addons",
            constraints=["keep HarvestMap"],
            desired_result="stable game",
            verification="launch and inspect errors",
        )
        for heading in ("Goal", "Context", "Constraints", "Desired result", "Verification"):
            self.assertIn(heading, optimized)
        self.assertIn("keep HarvestMap", optimized)

    def test_has_plain_language_templates_for_major_tasks(self) -> None:
        guide = PromptGuide()
        names = set(guide.templates())
        self.assertTrue({"general", "coding", "research", "system", "media", "automation"} <= names)


if __name__ == "__main__":
    unittest.main()
