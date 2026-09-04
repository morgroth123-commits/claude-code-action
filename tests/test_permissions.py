from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.host_policy import HostAction
from chatmpd.permissions import PermissionProfileStore
from chatmpd.platform_db import PlatformDatabase


class PermissionProfileStoreTest(unittest.TestCase):
    def test_autonomous_profile_still_requires_critical_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = PermissionProfileStore(PlatformDatabase(Path(directory) / "db.sqlite"))
            ordinary = store.evaluate(HostAction("files", "write", "C:/Users/Owner/Documents/a.txt"))
            critical = store.evaluate(HostAction("security", "disable", "Windows Defender"))
            self.assertFalse(ordinary.requires_confirmation)
            self.assertTrue(critical.requires_confirmation)

    def test_custom_profile_persists_confirmation_categories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db.sqlite"
            first = PermissionProfileStore(PlatformDatabase(path))
            first.save_custom("careful", confirmation_categories=["network", "desktop"])
            first.set_active("careful")
            second = PermissionProfileStore(PlatformDatabase(path))
            decision = second.evaluate(HostAction("network", "connect", "example"))
            self.assertTrue(decision.requires_confirmation)


if __name__ == "__main__":
    unittest.main()
