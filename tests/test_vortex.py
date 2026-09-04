from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from chatmpd.vortex import VortexInventory


class VortexInventoryTest(unittest.TestCase):
    def test_scans_version_games_profiles_mods_and_snapshot_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "startup.json").write_text('{"storeVersion":"2.1.1"}', "utf-8")
            game = root / "teso"
            (game / "profiles").mkdir(parents=True)
            (game / "mods").mkdir()
            (game / "snapshots").mkdir()
            (game / "profiles" / "p1.json").write_text("{}", "utf-8")
            (game / "mods" / "mod-a").mkdir()
            (game / "snapshots" / "snapshot.json").write_text(
                json.dumps([
                    {"basePath": "C:/Game", "entries": ["a", "b"]},
                    {"basePath": "C:/Mods", "entries": ["c"]},
                ]),
                "utf-8",
            )

            report = VortexInventory(root).scan()
            self.assertEqual(report.version, "2.1.1")
            self.assertEqual(len(report.games), 1)
            self.assertEqual(report.games[0].game_id, "teso")
            self.assertEqual(report.games[0].profile_count, 1)
            self.assertEqual(report.games[0].mod_count, 1)
            self.assertEqual(report.games[0].snapshot_entries, 3)
            self.assertEqual(report.games[0].snapshot_base_paths, ("C:/Game", "C:/Mods"))
