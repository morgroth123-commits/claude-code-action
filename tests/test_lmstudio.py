from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.lmstudio import BionicCompanion, LMStudioDiscovery, LMStudioProvider


class LMStudioIntegrationTest(unittest.TestCase):
    def test_discovers_bionic_bundled_lms_as_local_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lms = root / "Bionic" / "resources" / "app" / ".webpack-bionic" / "lms.exe"
            lms.parent.mkdir(parents=True)
            lms.write_bytes(b"exe")
            found = LMStudioDiscovery(extra_candidates=[lms]).discover()
            self.assertEqual(found.lms_path, lms)
            self.assertIn("bionic", found.source)

    def test_provider_health_uses_openai_models_endpoint(self) -> None:
        provider = LMStudioProvider("http://127.0.0.1:1234")
        provider._request = lambda method, path, payload=None: {
            "data": [{"id": "local-model"}]
        }
        self.assertTrue(provider.health())
        self.assertEqual(provider.models(), ("local-model",))

    def test_bionic_companion_reports_and_launches_installed_app(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "Bionic.exe"
            executable.write_bytes(b"exe")
            calls = []
            companion = BionicCompanion(
                executable=executable,
                launcher=lambda argv: calls.append(tuple(argv)),
            )
            self.assertTrue(companion.status()["installed"])
            companion.open()
            self.assertEqual(calls[0][0], str(executable))
            self.assertFalse(companion.status()["cloud_enabled_by_chatmpd"])


if __name__ == "__main__":
    unittest.main()
