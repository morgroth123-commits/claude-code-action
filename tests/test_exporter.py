from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from chatmpd.exporter import PackExporter


class PackExporterTest(unittest.TestCase):
    def test_creates_sanitized_pack_from_explicit_include_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extension = root / "safe-skill"
            extension.mkdir()
            (extension / "chatmpd-extension.toml").write_text(
                'id="safe.skill"\nname="Safe Skill"\nkind="skill"\nversion="1"\n',
                encoding="utf-8",
            )
            (extension / "skill.md").write_text("# Safe skill", encoding="utf-8")
            destination = root / "share.chatmpdpack"
            PackExporter().create_pack(destination, include_paths=[extension], metadata={"name": "Share"})
            with zipfile.ZipFile(destination) as archive:
                names = archive.namelist()
                self.assertIn("manifest.json", names)
                self.assertTrue(any(name.endswith("skill.md") for name in names))
                self.assertFalse(any("conversation" in name.casefold() for name in names))

    def test_rejects_private_state_and_explicit_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = root / "conversations"
            private.mkdir()
            (private / "chat.json").write_text("private", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "private"):
                PackExporter().create_pack(root / "bad.chatmpdpack", include_paths=[private])

            extension = root / "explicit"
            extension.mkdir()
            (extension / "chatmpd-extension.toml").write_text(
                'id="explicit.skill"\nname="Explicit"\nkind="skill"\nversion="1"\ncontent_categories=["explicit_sex"]\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "explicit"):
                PackExporter().create_pack(root / "bad2.chatmpdpack", include_paths=[extension])


if __name__ == "__main__":
    unittest.main()
