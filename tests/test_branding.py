from __future__ import annotations

import ast
import unittest
from pathlib import Path


class BrandingTest(unittest.TestCase):
    def test_mdright_is_the_canonical_desktop_and_mobile_icon(self) -> None:
        root = Path(__file__).resolve().parents[1]
        assets = root / "assets"
        self.assertTrue((assets / "MDRight-01.jpeg").is_file())
        self.assertTrue((assets / "chatmpd.ico").is_file())
        self.assertTrue((assets / "chatmpd-192.png").is_file())
        self.assertTrue((assets / "chatmpd-512.png").is_file())

        spec = ast.parse((root / "ChatMPD.spec").read_text(encoding="utf-8"))
        executable = next(
            node for node in ast.walk(spec)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "EXE"
        )
        keywords = {item.arg: item.value for item in executable.keywords}
        self.assertEqual(ast.literal_eval(keywords["icon"]), "assets/chatmpd.ico")


if __name__ == "__main__":
    unittest.main()
