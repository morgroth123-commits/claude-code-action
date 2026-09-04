from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from chatmpd.eso import EsoAddonManager, format_scan_report


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = io.BytesIO(body)

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _Opener:
    def __init__(self, responses: list[bytes]) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    def open(self, request: object, timeout: float) -> _Response:
        self.urls.append(request.full_url)  # type: ignore[attr-defined]
        return _Response(self.responses.pop(0))


def _write_manifest(
    root: Path,
    folder: str,
    addon_id: str,
    *,
    api: int = 101050,
    version: int = 1,
    depends: str = "",
    payload: bool = True,
) -> None:
    directory = root / "AddOns" / folder
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        f"## Title: {addon_id}",
        f"## APIVersion: {api}",
        f"## AddOnVersion: {version}",
    ]
    if depends:
        lines.append(f"## DependsOn: {depends}")
    lines.append("main.lua")
    (directory / f"{addon_id}.txt").write_text("\n".join(lines), encoding="utf-8")
    if payload:
        (directory / "main.lua").write_text("return true\n", encoding="utf-8")


class EsoScannerTest(unittest.TestCase):
    def test_finds_dependencies_missing_files_duplicates_and_outdated_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            live = Path(directory) / "live"
            (live / "AddOns").mkdir(parents=True)
            (live / "AddOnSettings.txt").write_text(
                "#Version 101050\nMain 1\nLibThing 0\nGhost 1\n", encoding="utf-8"
            )
            _write_manifest(
                live, "Main", "Main", api=101040, depends="LibThing>=2 MissingLib"
            )
            _write_manifest(live, "LibThing", "LibThing", version=1)
            _write_manifest(live, "Broken", "Broken", payload=False)
            _write_manifest(live, "CopyOne", "Duplicate")
            _write_manifest(live, "CopyTwo", "Duplicate")

            report = EsoAddonManager(
                live,
                eso_detector=lambda: False,
                minion_detector=lambda: False,
                backup_root=live / "backups",
                registry_path=live / "registry.json",
            ).scan()
            codes = {issue.code for issue in report.issues}

            self.assertIn("outdated_api", codes)
            self.assertIn("dependency_disabled", codes)
            self.assertIn("dependency_missing", codes)
            self.assertIn("dependency_too_old", codes)
            self.assertIn("duplicate_id", codes)
            self.assertIn("orphan_setting", codes)
            self.assertIn("3 critical", format_scan_report(report))

    def test_scans_modern_addon_manifest_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            live = Path(directory) / "live"
            addons = live / "AddOns"
            (addons / "Main").mkdir(parents=True)
            (addons / "LibAddonMenu-2.0").mkdir(parents=True)
            (live / "AddOnSettings.txt").write_text(
                "#Version 101050\nMain 1\nLibAddonMenu-2.0 1\n", encoding="utf-8"
            )
            (addons / "Main" / "Main.txt").write_text(
                "## Title: Main\n## APIVersion: 101050\n"
                "## DependsOn: LibAddonMenu-2.0\nmain.lua\n",
                encoding="utf-8",
            )
            (addons / "Main" / "main.lua").write_text("return true\n", encoding="utf-8")
            (addons / "LibAddonMenu-2.0" / "LibAddonMenu-2.0.addon").write_text(
                "## Title: LibAddonMenu\n## APIVersion: 101050\n"
                "## IsLibrary: true\nlib.lua\n",
                encoding="utf-8",
            )
            (addons / "LibAddonMenu-2.0" / "lib.lua").write_text(
                "return true\n", encoding="utf-8"
            )

            report = EsoAddonManager(live).scan()

            self.assertEqual(len(report.manifests), 2)
            self.assertFalse(
                any(issue.kind == "missing_dependency" for issue in report.issues)
            )
    def test_repairs_disabled_dependency_and_obvious_nested_package_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            live = Path(directory) / "live"
            (live / "AddOns").mkdir(parents=True)
            (live / "AddOnSettings.txt").write_text(
                "#Version 101050\nMain 1\nLibThing 0\nOdd 1\n", encoding="utf-8"
            )
            _write_manifest(live, "Main", "Main", depends="LibThing")
            _write_manifest(live, "LibThing", "LibThing")
            nested = live / "AddOns" / "1784248069-Odd" / "Odd"
            nested.mkdir(parents=True)
            (nested / "Odd.txt").write_text(
                "## Title: Odd\n## APIVersion: 101050\nOdd.lua\n", encoding="utf-8"
            )
            (nested / "Odd.lua").write_text("return true\n", encoding="utf-8")
            manager = EsoAddonManager(
                live,
                eso_detector=lambda: False,
                minion_detector=lambda: False,
                backup_root=live / "backups",
                registry_path=live / "registry.json",
            )

            result = manager.repair_safe_issues()

            self.assertEqual(result.report.repairable_count, 0)
            self.assertIn("LibThing 1", (live / "AddOnSettings.txt").read_text())
            self.assertTrue((live / "AddOns" / "Odd" / "Odd.txt").is_file())
            self.assertIsNotNone(result.backup_directory)
            self.assertTrue((result.backup_directory / "AddOnSettings.txt").is_file())
            self.assertTrue(
                (result.backup_directory / "misnested" / "1784248069-Odd").is_dir()
            )

    def test_refuses_repairs_while_eso_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            live = Path(directory) / "live"
            (live / "AddOns").mkdir(parents=True)
            manager = EsoAddonManager(live, eso_detector=lambda: True)
            with self.assertRaisesRegex(RuntimeError, "Close ESO"):
                manager.repair_safe_issues()

    def test_imports_minion_registry_and_checks_esoui_updates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live"
            (live / "AddOns" / "Example").mkdir(parents=True)
            minion = root / "minion.xml"
            minion.write_text(
                "<configuration><games><game game-id='ESO' addon-path='"
                + str(live / "AddOns")
                + "'><addons><addon uid='123' ui-version='1.0'><dirs><dir>Example</dir>"
                "</dirs></addon></addons></game></games></configuration>",
                encoding="utf-8",
            )
            body = json.dumps(
                [
                    {
                        "UID": "123",
                        "UIVersion": "2.0",
                        "UIName": "Example Addon",
                        "UIFileName": "Example-2.zip",
                        "UIDownload": "https://cdn.esoui.com/downloads/getfile.php?id=123",
                    }
                ]
            ).encode()
            manager = EsoAddonManager(
                live,
                minion_config=minion,
                opener=_Opener([body]),
                registry_path=root / "registry.json",
            )

            updates = manager.check_updates()

            self.assertEqual(len(updates), 1)
            self.assertTrue(updates[0].update_available)
            self.assertEqual(updates[0].installed_version, "1.0")

    def test_installs_validated_zip_and_rolls_existing_folder_into_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live"
            old = live / "AddOns" / "Example"
            old.mkdir(parents=True)
            (old / "old.lua").write_text("old", encoding="utf-8")
            metadata = json.dumps(
                [
                    {
                        "UID": "123",
                        "UIVersion": "2.0",
                        "UIName": "Example",
                        "UIFileName": "Example.zip",
                        "UIDownload": "https://cdn.esoui.com/downloads/getfile.php?id=123",
                    }
                ]
            ).encode()
            archive_stream = io.BytesIO()
            with zipfile.ZipFile(archive_stream, "w") as archive:
                archive.writestr("Example/Example.txt", "## Title: Example\n## APIVersion: 101050\nmain.lua\n")
                archive.writestr("Example/main.lua", "return true\n")
            manager = EsoAddonManager(
                live,
                eso_detector=lambda: False,
                minion_detector=lambda: False,
                opener=_Opener([metadata, archive_stream.getvalue()]),
                backup_root=root / "backups",
                registry_path=root / "registry.json",
            )

            result = manager.install_or_update(123)

            self.assertTrue((old / "main.lua").is_file())
            self.assertFalse((old / "old.lua").exists())
            self.assertTrue((result.backup_directory / "previous" / "Example" / "old.lua").is_file())
            self.assertIn('"uid": 123', (root / "registry.json").read_text())


if __name__ == "__main__":
    unittest.main()
