from __future__ import annotations

import unittest
from queue import Queue
from threading import Event

from chatmpd.orchestrator import CommandResult
from chatmpd.universal_gui import UniversalController, local_mobile_url


class UniversalControllerTest(unittest.TestCase):
    def test_one_composer_runs_any_capability_in_background(self) -> None:
        scheduled: Queue[object] = Queue()
        snapshots = []
        started = Event()
        release = Event()

        def command(text: str, workspace: str | None = None) -> CommandResult:
            self.assertEqual(text, "Scan ESO addons")
            self.assertIsNone(workspace)
            started.set()
            release.wait(2)
            return CommandResult("eso", "ESO healthy", {"addon_count": 173})

        controller = UniversalController(
            command_handler=command,
            schedule=scheduled.put,
            publish=snapshots.append,
        )
        self.assertTrue(controller.start("Scan ESO addons", ""))
        self.assertTrue(started.wait(1))
        self.assertTrue(controller.busy)
        self.assertEqual(snapshots[-1].status, "Working locally...")

        release.set()
        scheduled.get(timeout=2)()
        self.assertFalse(controller.busy)
        self.assertEqual(snapshots[-1].capability, "eso")
        self.assertEqual(snapshots[-1].message, "ESO healthy")

    def test_blank_command_and_overlapping_work_are_rejected(self) -> None:
        snapshots = []
        controller = UniversalController(
            command_handler=lambda text, workspace=None: CommandResult("chat", "ok"),
            schedule=lambda callback: callback(),
            publish=snapshots.append,
        )
        self.assertFalse(controller.start("   ", ""))
        self.assertIn("Describe", snapshots[-1].status)

    def test_local_mobile_url_prefers_private_ipv4(self) -> None:
        url = local_mobile_url(
            8765,
            hostname="Vader",
            resolver=lambda host: [
                (None, None, None, None, ("127.0.0.1", 0)),
                (None, None, None, None, ("192.168.1.50", 0)),
            ],
        )
        self.assertEqual(url, "http://192.168.1.50:8765/")


if __name__ == "__main__":
    unittest.main()
