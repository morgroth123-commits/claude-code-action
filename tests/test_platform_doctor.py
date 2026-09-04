from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.extensions import ExtensionManager
from chatmpd.platform_doctor import PlatformDoctor
from chatmpd.platform_paths import PlatformPaths


class PlatformDoctorTest(unittest.TestCase):
    def test_reports_broken_extension_and_repairs_only_managed_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "ChatMPD"
            paths = PlatformPaths(root)
            bad = paths.extensions / "broken"
            bad.mkdir(parents=True)
            (bad / "skill.toml").write_text(
                '[extension]\nid="broken.one"\nname="Broken"\nkind="skill"\nentrypoint="missing.md"\n',
                encoding="utf-8",
            )
            doctor = PlatformDoctor(paths=paths, extensions=ExtensionManager(paths.extensions))
            report = doctor.run()
            self.assertTrue(any(check.name == "extensions" and not check.ready for check in report.checks))
            repairs = doctor.repair()
            self.assertTrue(paths.data.is_dir())
            self.assertFalse(any("security" in action.casefold() or "firewall" in action.casefold() for action in repairs))


if __name__ == "__main__":
    unittest.main()
