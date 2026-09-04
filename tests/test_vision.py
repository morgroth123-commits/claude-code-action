from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.vision import LocalVision


class VisionTest(unittest.TestCase):
    def test_screenshot_creates_managed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def capture(path: Path) -> None:
                path.write_bytes(b"PNG")
            vision = LocalVision(root, capture_backend=capture)
            artifact = vision.capture_screen()
            self.assertTrue(artifact.is_file())
            self.assertEqual(artifact.parent, root.resolve())

    def test_no_local_vision_model_never_falls_back_to_cloud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vision = LocalVision(Path(directory), provider=None, capture_backend=lambda path: path.write_bytes(b"PNG"))
            self.assertFalse(vision.health()["ready"])
            with self.assertRaisesRegex(RuntimeError, "local vision"):
                vision.analyze(Path(directory) / "anything.png", "describe")


if __name__ == "__main__":
    unittest.main()
