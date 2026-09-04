from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.packs import CapabilityPackManager
from chatmpd.platform_db import PlatformDatabase


class CapabilityPackManagerTest(unittest.TestCase):
    def test_install_uninstall_and_restart_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packs = root / "packs"
            packs.mkdir()
            (packs / "dev.toml").write_text(
                '[pack]\nid="developer"\nname="Developer"\ndescription="Coding tools"\ncapabilities=["coding","git"]\n',
                encoding="utf-8",
            )
            db_path = root / "db.sqlite"
            first = CapabilityPackManager(packs, PlatformDatabase(db_path))
            pack = first.install("developer")
            self.assertTrue(pack.installed)
            second = CapabilityPackManager(packs, PlatformDatabase(db_path))
            self.assertTrue(second.get("developer").installed)
            self.assertTrue(second.uninstall("developer"))
            self.assertFalse(second.get("developer").installed)


if __name__ == "__main__":
    unittest.main()
