from __future__ import annotations

import unittest
from datetime import UTC, datetime

from chatmpd.automation_engine import AutomationScheduler


class _Store:
    def __init__(self) -> None:
        self.calls = []

    def run_due(self, now, runner):
        self.calls.append(now)
        return (runner("scheduled command"),)


class AutomationSchedulerTest(unittest.TestCase):
    def test_run_once_uses_store_and_runner(self) -> None:
        store = _Store()
        calls = []
        scheduler = AutomationScheduler(store, lambda command: calls.append(command) or "ok")
        when = datetime(2026, 9, 4, 6, 0, tzinfo=UTC)
        result = scheduler.run_once(when)
        self.assertEqual(calls, ["scheduled command"])
        self.assertEqual(result, ("ok",))
        self.assertEqual(store.calls, [when])

    def test_poll_interval_is_bounded(self) -> None:
        with self.assertRaisesRegex(ValueError, "poll_seconds"):
            AutomationScheduler(_Store(), lambda _command: None, poll_seconds=0.1)
