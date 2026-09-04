from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.extension_wizard import ExtensionWizard
from chatmpd.extensions import ExtensionManager


class ExtensionWizardTest(unittest.TestCase):
    def test_generates_valid_skill_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wizard = ExtensionWizard(root)
            folder = wizard.create_skill(
                "Skyrim Conflict Helper",
                capability_id="modding.skyrim.conflicts",
                description="Diagnose Skyrim mod conflicts.",
            )
            self.assertTrue((folder / "skill.toml").is_file())
            self.assertTrue((folder / "SKILL.md").is_file())
            discovered = ExtensionManager(root).discover()
            self.assertEqual(discovered[0].capability_id, "modding.skyrim.conflicts")
            self.assertEqual(discovered[0].health, "ready")

    def test_refuses_explicit_sex_skill_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "explicit"):
                ExtensionWizard(Path(directory)).create_skill(
                    "Explicit", capability_id="media.explicit", content_categories=["explicit_sex"]
                )


if __name__ == "__main__":
    unittest.main()
