from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.platform_db import PlatformDatabase
from chatmpd.workflows import WorkflowStore


class WorkflowStoreTest(unittest.TestCase):
    def test_save_restart_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db = PlatformDatabase(Path(directory) / "db.sqlite")
            first = WorkflowStore(db)
            saved = first.save("System check", "check system health", workspace=None)
            second = WorkflowStore(PlatformDatabase(Path(directory) / "db.sqlite"))
            restored = second.get(saved.workflow_id)
            calls = []
            result = second.replay(restored.workflow_id, lambda text, workspace=None: calls.append((text, workspace)) or "ok")
            self.assertEqual(result, "ok")
            self.assertEqual(calls, [("check system health", None)])
            self.assertEqual(second.list()[0].name, "System check")


if __name__ == "__main__":
    unittest.main()
