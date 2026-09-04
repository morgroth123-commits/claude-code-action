from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.activity import ActivityLog
from chatmpd.platform_db import PlatformDatabase


class ActivityLogTest(unittest.TestCase):
    def test_records_bounded_evidence_without_private_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log = ActivityLog(PlatformDatabase(Path(directory) / "db.sqlite"))
            event = log.record("tool", "Ran verification", details={"exit_code": 0})
            self.assertEqual(event.kind, "tool")
            restored = log.list(limit=10)[0]
            self.assertEqual(restored.summary, "Ran verification")
            self.assertEqual(restored.details["exit_code"], 0)
            with self.assertRaisesRegex(ValueError, "private reasoning"):
                log.record("reasoning", "hidden chain", details={})


if __name__ == "__main__":
    unittest.main()
