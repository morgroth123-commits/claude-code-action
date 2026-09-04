from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from chatmpd.knowledge import KnowledgeLibrary, extract_text
from chatmpd.platform_db import PlatformDatabase


class KnowledgeLibraryTest(unittest.TestCase):
    def test_indexes_text_and_returns_source_provenance_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "guide.md"
            source.write_text("HarvestMap stores resource locations for ESO gathering.", encoding="utf-8")
            db_path = root / "platform.db"
            library = KnowledgeLibrary(PlatformDatabase(db_path))
            record = library.ingest(source)
            hits = library.search("resource locations")
            self.assertEqual(hits[0].source_id, record.source_id)
            self.assertEqual(hits[0].path, source.resolve())

            restarted = KnowledgeLibrary(PlatformDatabase(db_path))
            self.assertIn("HarvestMap", restarted.search("gathering")[0].text)

    def test_extracts_csv_and_docx_without_executing_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "items.csv"
            csv_path.write_text("name,value\nalpha,42\n", encoding="utf-8")
            self.assertIn("alpha", extract_text(csv_path))
            docx_path = root / "note.docx"
            with zipfile.ZipFile(docx_path, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    '<w:body><w:p><w:r><w:t>Persistent local knowledge</w:t></w:r></w:p></w:body></w:document>',
                )
            self.assertIn("Persistent local knowledge", extract_text(docx_path))

    def test_rejects_unsupported_or_oversized_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unknown = root / "binary.exe"
            unknown.write_bytes(b"abc")
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                extract_text(unknown)
            large = root / "large.txt"
            large.write_bytes(b"x" * 1025)
            with self.assertRaisesRegex(ValueError, "too large"):
                extract_text(large, max_bytes=1024)


if __name__ == "__main__":
    unittest.main()
