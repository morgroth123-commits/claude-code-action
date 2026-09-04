from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from chatmpd.automation_engine import AutomationStore
from chatmpd.platform_db import PlatformDatabase


class AutomationStoreTest(unittest.TestCase):
    def test_interval_due_run_and_restart_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db.sqlite"
            store = AutomationStore(PlatformDatabase(path))
            now = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
            record = store.create(
                "Health watch", "check system health", interval_seconds=3600,
                start_at=now - timedelta(seconds=1),
            )
            calls = []
            runs = store.run_due(now, lambda text: calls.append(text) or "healthy")
            self.assertEqual(calls, ["check system health"])
            self.assertEqual(runs[0].automation_id, record.automation_id)
            restarted = AutomationStore(PlatformDatabase(path))
            self.assertEqual(restarted.get(record.automation_id).name, "Health watch")
            self.assertGreater(restarted.get(record.automation_id).next_run, now)

    def test_condition_match_is_reported_without_changing_cadence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db.sqlite"
            store = AutomationStore(PlatformDatabase(path))
            now = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
            record = store.create(
                "Wait for ready", "status", interval_seconds=60,
                condition_contains="ready", start_at=now,
            )
            runs = store.run_due(now, lambda _text: "system is READY")
            self.assertTrue(runs[0].condition_met)
            self.assertEqual(runs[0].automation_id, record.automation_id)


if __name__ == "__main__":
    unittest.main()
