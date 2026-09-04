from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GenericSharingUiTest(unittest.TestCase):
    def test_shareable_user_interfaces_do_not_hardcode_vader(self) -> None:
        paths = (
            ROOT / "chatmpd" / "web" / "index.html",
            ROOT / "chatmpd" / "web" / "app.js",
            ROOT / "chatmpd" / "mobile_assets.py",
            ROOT / "chatmpd" / "mobile_gateway.py",
        )
        for path in paths:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("Vader", text)
                self.assertNotIn("C:\\\\Users\\\\Owner", text)


if __name__ == "__main__":
    unittest.main()
