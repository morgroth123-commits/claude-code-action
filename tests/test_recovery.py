from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.platform_db import PlatformDatabase
from chatmpd.recovery import RecoveryCenter


class RecoveryCenterTest(unittest.TestCase):
    def test_snapshot_and_explicit_rollback_restore_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "settings.ini"
            target.write_text("before", encoding="utf-8")
            center = RecoveryCenter(
                PlatformDatabase(root / "db.sqlite"),
                root / "recovery",
            )
            snapshot = center.snapshot([target], label="before change")
            target.write_text("after", encoding="utf-8")
            restored = center.rollback(snapshot.snapshot_id)
            self.assertEqual(target.read_text(encoding="utf-8"), "before")
            self.assertEqual(restored[0], target.resolve())
            self.assertEqual(center.list()[0].label, "before change")

    def test_rejects_missing_or_directory_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            center = RecoveryCenter(PlatformDatabase(root / "db.sqlite"), root / "r")
            with self.assertRaises(ValueError):
                center.snapshot([root], label="bad")


if __name__ == "__main__":
    unittest.main()
