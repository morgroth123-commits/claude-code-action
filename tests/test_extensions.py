from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.extensions import ExtensionManager


class ExtensionManagerTest(unittest.TestCase):
    def test_discovers_skill_and_reports_missing_entrypoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / "good"
            good.mkdir()
            (good / "skill.toml").write_text(
                '[extension]\nid="skill.echo"\nname="Echo skill"\nversion="1.0"\n'
                'kind="skill"\ndescription="Echo guidance"\nentrypoint="SKILL.md"\n',
                encoding="utf-8",
            )
            (good / "SKILL.md").write_text("# Echo\nUse concise replies.\n", encoding="utf-8")
            broken = root / "broken"
            broken.mkdir()
            (broken / "skill.toml").write_text(
                '[extension]\nid="skill.broken"\nname="Broken"\nversion="1"\n'
                'kind="skill"\nentrypoint="missing.md"\n', encoding="utf-8"
            )

            items = {item.capability_id: item for item in ExtensionManager(root).discover()}
            self.assertEqual(items["skill.echo"].health, "ready")
            self.assertEqual(items["skill.echo"].kind, "skill")
            self.assertEqual(items["skill.broken"].health, "broken")
