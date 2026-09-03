from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


class PackageMetadataTest(unittest.TestCase):
    def test_project_is_named_chatmpd_and_uses_the_desktop_entrypoint(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with (root / "pyproject.toml").open("rb") as handle:
            metadata = tomllib.load(handle)

        self.assertEqual(metadata["project"]["name"], "ChatMPD")
        self.assertRegex(metadata["project"]["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(
            metadata["project"]["scripts"]["chatmpd"],
            "chatmpd.app:main",
        )
        self.assertEqual(metadata["project"]["dependencies"], [])


if __name__ == "__main__":
    unittest.main()
