from __future__ import annotations

import unittest

from chatmpd.doctrine import (
    coding_agent_prompt,
    eso_specialist_prompt,
    general_assistant_prompt,
    media_specialist_prompt,
)


class DoctrineTest(unittest.TestCase):
    def test_general_prompt_is_distinctive_local_and_evidence_grounded(self) -> None:
        prompt = general_assistant_prompt().casefold()
        self.assertIn("chatmpd", prompt)
        self.assertIn("local", prompt)
        self.assertIn("evidence", prompt)
        self.assertIn("third-party", prompt)
        self.assertIn("credentials", prompt)
        self.assertIn("finish", prompt)

    def test_coding_prompt_preserves_work_and_requires_fresh_verification(self) -> None:
        check = ["/usr/bin/python3", "-m", "unittest"]
        prompt = coding_agent_prompt([check]).casefold()
        self.assertIn("preserve", prompt)
        self.assertIn("dirty", prompt)
        self.assertIn("exactly one", prompt)
        self.assertIn("fresh verification", prompt)
        self.assertIn("/usr/bin/python3", prompt)

    def test_eso_prompt_prioritizes_evidence_backups_and_required_addons(self) -> None:
        prompt = eso_specialist_prompt().casefold()
        self.assertIn("minion", prompt)
        self.assertIn("bugcatcher", prompt)
        self.assertIn("backup", prompt)
        self.assertIn("required addons", prompt)
        self.assertIn("never blindly delete", prompt)

    def test_media_prompt_defaults_ambiguous_erotica_to_fictional_adults(self) -> None:
        prompt = media_specialist_prompt().casefold()
        self.assertIn("fictional adults", prompt)
        self.assertIn("consenting", prompt)
        self.assertIn("identifiable real people", prompt)
        self.assertIn("closest permitted", prompt)
        self.assertIn("sensual", prompt)


if __name__ == "__main__":
    unittest.main()
