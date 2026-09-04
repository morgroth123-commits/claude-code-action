from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.system_capability import SystemInspector


class SystemInspectorTest(unittest.TestCase):
    def test_snapshot_is_bounded_dependency_free_and_reports_core_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inspector = SystemInspector(
                disk_root=Path(directory),
                memory_probe=lambda: (32 * 1024**3, 12 * 1024**3),
                gpu_probe=lambda: {
                    "name": "RTX 3060",
                    "vram_total_mib": 12288,
                    "vram_used_mib": 1024,
                },
            )
            snapshot = inspector.snapshot()
            self.assertGreaterEqual(snapshot.cpu_logical, 1)
            self.assertEqual(snapshot.memory_total_bytes, 32 * 1024**3)
            self.assertEqual(snapshot.memory_available_bytes, 12 * 1024**3)
            self.assertEqual(snapshot.gpu["name"], "RTX 3060")
            self.assertGreater(snapshot.disk_total_bytes, 0)
            self.assertGreaterEqual(snapshot.disk_free_bytes, 0)
