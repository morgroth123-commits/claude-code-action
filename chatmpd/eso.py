"""ESO add-on inventory, compatibility diagnosis, and reversible management."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Literal
from uuid import uuid4

from .runtime import is_eso_running


Severity = Literal["critical", "warning", "info"]
_MANIFEST_LIMIT = 1_048_576
_METADATA_LIMIT = 8_388_608
_DOWNLOAD_LIMIT = 536_870_912
_ARCHIVE_EXPANDED_LIMIT = 1_073_741_824
_MMOUI_API = "https://api.mmoui.com/v3/game/ESO"


def _local_appdata() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else Path.home() / "AppData" / "Local"


def _default_backup_root() -> Path:
    return _local_appdata() / "ChatMPD" / "eso-backups"


def _default_registry_path() -> Path:
    return _local_appdata() / "ChatMPD" / "eso" / "managed-addons.json"


@dataclass(frozen=True)
class Dependency:
    addon_id: str
    minimum_version: int | None = None


@dataclass(frozen=True)
class AddonManifest:
    addon_id: str
    title: str
    manifest_path: str
    package_directory: str
    api_versions: tuple[int, ...]
    addon_version: int | None
    display_version: str
    dependencies: tuple[Dependency, ...]
    optional_dependencies: tuple[Dependency, ...]
    is_library: bool
    enabled: bool
    missing_payloads: tuple[str, ...]


@dataclass(frozen=True)
class AddonIssue:
    code: str
    severity: Severity
    addon_id: str
    message: str
    repairable: bool = False
    details: tuple[str, ...] = ()


@dataclass(frozen=True)
class EsoScanReport:
    live_directory: Path
    addons_directory: Path
    current_api: int | None
    manifests: tuple[AddonManifest, ...]
    issues: tuple[AddonIssue, ...]
    enabled_ids: tuple[str, ...]
    scanned_at: str

    @property
    def critical_count(self) -> int:
        return sum(issue.severity == "critical" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)

    @property
    def repairable_count(self) -> int:
        return sum(issue.repairable for issue in self.issues)


@dataclass(frozen=True)
class ManagedAddon:
    uid: int
    name: str
    installed_version: str
    directories: tuple[str, ...]


@dataclass(frozen=True)
class AddonUpdate:
    uid: int
    name: str
    installed_version: str
    available_version: str
    download_url: str
    filename: str
    directories: tuple[str, ...]
    update_available: bool


@dataclass(frozen=True)
class RepairResult:
    actions: tuple[str, ...]
    backup_directory: Path | None
    report: EsoScanReport


@dataclass(frozen=True)
class InstallResult:
    uid: int
    name: str
    version: str
    installed_directories: tuple[str, ...]
    backup_directory: Path


class EsoAddonManager:
    """Manage an ESO add-on directory without executing downloaded add-on code."""

    def __init__(
        self,
        live_directory: Path | None = None,
        *,
        minion_config: Path | None = None,
        backup_root: Path | None = None,
        registry_path: Path | None = None,
        eso_detector: Callable[[], bool] = is_eso_running,
        minion_detector: Callable[[], bool] | None = None,
        opener: Any | None = None,
    ) -> None:
        self.live_directory = resolve_eso_live_directory(live_directory)
        self.addons_directory = _child_case_insensitive(
            self.live_directory, "AddOns"
        )
        self.settings_path = _child_case_insensitive(
            self.live_directory, "AddOnSettings.txt", required=False
        )
        self.minion_config = Path(
            minion_config or (Path.home() / ".minion" / "minion.xml")
        )
        self.backup_root = Path(backup_root or _default_backup_root())
        self.registry_path = Path(registry_path or _default_registry_path())
        self._eso_detector = eso_detector
        self._minion_detector = minion_detector or _is_minion_running
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )

    def scan(self) -> EsoScanReport:
        statuses, current_api = _read_addon_settings(self.settings_path)
        manifests = _scan_manifests(self.addons_directory, statuses)
        issues = _diagnose(
            self.addons_directory, manifests, statuses, current_api
        )
        enabled_ids = sorted(
            (addon_id for addon_id, values in statuses.items() if 1 in values),
            key=str.casefold,
        )
        return EsoScanReport(
            live_directory=self.live_directory,
            addons_directory=self.addons_directory,
            current_api=current_api,
            manifests=tuple(manifests),
            issues=tuple(issues),
            enabled_ids=tuple(enabled_ids),
            scanned_at=datetime.now(UTC).isoformat(),
        )

    def repair_safe_issues(
        self, report: EsoScanReport | None = None
    ) -> RepairResult:
        self._require_idle_game_files()
        current = report or self.scan()
        repairs = [issue for issue in current.issues if issue.repairable]
        if not repairs:
            return RepairResult((), None, current)

        backup = self._new_backup_directory("repair")
        actions: list[str] = []
        disabled_dependencies = {
            issue.details[0]
            for issue in repairs
            if issue.code == "dependency_disabled" and issue.details
        }
        if disabled_dependencies:
            if not self.settings_path.is_file():
                raise RuntimeError("AddOnSettings.txt is missing; no settings were changed")
            copied = backup / "AddOnSettings.txt"
            shutil.copy2(self.settings_path, copied)
            _enable_addons_in_settings(self.settings_path, disabled_dependencies)
            actions.append(
                "Enabled required dependencies: "
                + ", ".join(sorted(disabled_dependencies, key=str.casefold))
            )

        for issue in repairs:
            if issue.code != "nested_package" or len(issue.details) != 2:
                continue
            wrapper_name, child_name = issue.details
            wrapper = self.addons_directory / wrapper_name
            child = wrapper / child_name
            target = self.addons_directory / child_name
            if not wrapper.is_dir() or not child.is_dir() or target.exists():
                continue
            quarantined = backup / "misnested" / wrapper_name
            quarantined.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(wrapper), str(quarantined))
            try:
                shutil.copytree(quarantined / child_name, target)
            except BaseException:
                if target.exists():
                    shutil.rmtree(target)
                shutil.move(str(quarantined), str(wrapper))
                raise
            actions.append(
                f"Moved {child_name} to the ESO AddOns root; original kept in backup"
            )

        (backup / "repair.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "created_at": datetime.now(UTC).isoformat(),
                    "live_directory": str(self.live_directory),
                    "actions": actions,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return RepairResult(tuple(actions), backup, self.scan())

    def managed_addons(self) -> tuple[ManagedAddon, ...]:
        by_uid: dict[int, ManagedAddon] = {}
        if self.minion_config.is_file():
            try:
                root = ET.parse(self.minion_config).getroot()
                for game in root.findall("./games/game"):
                    addon_path = game.attrib.get("addon-path", "")
                    if not _same_path(addon_path, self.addons_directory):
                        continue
                    for addon in game.findall("./addons/addon"):
                        try:
                            uid = int(addon.attrib["uid"])
                        except (KeyError, ValueError):
                            continue
                        directories = tuple(
                            _safe_directory_name(node.text or "")
                            for node in addon.findall("./dirs/dir")
                            if _is_safe_directory_name(node.text or "")
                        )
                        if not directories:
                            continue
                        by_uid[uid] = ManagedAddon(
                            uid,
                            directories[0],
                            addon.attrib.get("ui-version", "unknown"),
                            directories,
                        )
            except (ET.ParseError, OSError):
                pass

        for addon in _read_local_registry(self.registry_path):
            by_uid[addon.uid] = addon
        return tuple(sorted(by_uid.values(), key=lambda item: item.name.casefold()))

    def check_updates(self) -> tuple[AddonUpdate, ...]:
        managed = self.managed_addons()
        if not managed:
            return ()
        metadata: dict[int, dict[str, Any]] = {}
        uids = [addon.uid for addon in managed]
        for start in range(0, len(uids), 50):
            joined = ",".join(str(uid) for uid in uids[start : start + 50])
            data = self._request_json(f"{_MMOUI_API}/filedetails/{joined}.json")
            if not isinstance(data, list):
                raise RuntimeError("ESOUI returned unexpected update metadata")
            for item in data:
                if not isinstance(item, dict):
                    continue
                try:
                    metadata[int(item["UID"])] = item
                except (KeyError, TypeError, ValueError):
                    continue

        updates: list[AddonUpdate] = []
        for addon in managed:
            item = metadata.get(addon.uid)
            if item is None:
                continue
            available = str(item.get("UIVersion", "unknown")).strip() or "unknown"
            name = str(item.get("UIName", addon.name)).strip() or addon.name
            download = _trusted_download_url(str(item.get("UIDownload", "")))
            filename = Path(str(item.get("UIFileName", f"{addon.uid}.zip"))).name
            updates.append(
                AddonUpdate(
                    addon.uid,
                    name,
                    addon.installed_version,
                    available,
                    download,
                    filename,
                    addon.directories,
                    _version_key(available) != _version_key(addon.installed_version),
                )
            )
        return tuple(sorted(updates, key=lambda item: item.name.casefold()))

    def install_or_update(self, uid: int) -> InstallResult:
        self._require_idle_game_files()
        numeric_uid = int(uid)
        if numeric_uid <= 0:
            raise ValueError("ESOUI add-on ID must be a positive number")
        data = self._request_json(
            f"{_MMOUI_API}/filedetails/{numeric_uid}.json"
        )
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise RuntimeError(f"ESOUI add-on {numeric_uid} was not found")
        metadata = data[0]
        download_url = _trusted_download_url(str(metadata.get("UIDownload", "")))
        name = str(metadata.get("UIName", numeric_uid)).strip() or str(numeric_uid)
        version = str(metadata.get("UIVersion", "unknown")).strip() or "unknown"

        with tempfile.TemporaryDirectory(prefix="ChatMPD-ESO-") as directory:
            staging_root = Path(directory)
            archive = staging_root / "addon.zip"
            self._download(download_url, archive)
            extracted = staging_root / "extracted"
            directories = _extract_validated_archive(archive, extracted)
            backup = self._new_backup_directory(f"addon-{numeric_uid}")
            moved_old: list[tuple[Path, Path]] = []
            installed: list[Path] = []
            try:
                for directory_name in directories:
                    target = self.addons_directory / directory_name
                    source = extracted / directory_name
                    if target.exists():
                        old = backup / "previous" / directory_name
                        old.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(target), str(old))
                        moved_old.append((old, target))
                    shutil.move(str(source), str(target))
                    installed.append(target)
            except BaseException:
                for target in reversed(installed):
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink(missing_ok=True)
                for old, target in reversed(moved_old):
                    if old.exists():
                        shutil.move(str(old), str(target))
                raise

        managed = {
            addon.uid: addon for addon in _read_local_registry(self.registry_path)
        }
        managed[numeric_uid] = ManagedAddon(
            numeric_uid, name, version, tuple(directories)
        )
        _write_local_registry(self.registry_path, managed.values())
        (backup / "install.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "created_at": datetime.now(UTC).isoformat(),
                    "uid": numeric_uid,
                    "name": name,
                    "version": version,
                    "directories": directories,
                    "download_url": download_url,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return InstallResult(numeric_uid, name, version, tuple(directories), backup)

    def _request_json(self, url: str) -> Any:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "ChatMPD/0.2"},
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=30.0) as response:
                body = response.read(_METADATA_LIMIT + 1)
        except OSError as error:
            raise RuntimeError(f"Could not reach ESOUI: {error}") from error
        if len(body) > _METADATA_LIMIT:
            raise RuntimeError("ESOUI metadata response was unexpectedly large")
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("ESOUI returned invalid update metadata") from error

    def _download(self, url: str, destination: Path) -> None:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/zip", "User-Agent": "ChatMPD/0.2"},
            method="GET",
        )
        try:
            with self._opener.open(request, timeout=120.0) as response:
                with destination.open("wb") as stream:
                    total = 0
                    while True:
                        block = response.read(1_048_576)
                        if not block:
                            break
                        total += len(block)
                        if total > _DOWNLOAD_LIMIT:
                            raise RuntimeError("The add-on download exceeded 512 MiB")
                        stream.write(block)
        except OSError as error:
            raise RuntimeError(f"Could not download the ESO add-on: {error}") from error
        if not zipfile.is_zipfile(destination):
            raise RuntimeError("ESOUI did not return a valid ZIP archive")

    def _require_idle_game_files(self) -> None:
        if self._eso_detector():
            raise RuntimeError("Close ESO before changing add-on files.")
        if self._minion_detector():
            raise RuntimeError("Close Minion before changing add-on files.")

    def _new_backup_directory(self, label: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = self.backup_root / f"{stamp}-{label}-{uuid4().hex[:8]}"
        destination.mkdir(parents=True, exist_ok=False)
        return destination


def discover_eso_live_directory() -> Path:
    """Return the first verified ESO live directory on this Windows profile."""

    minion = Path.home() / ".minion" / "minion.xml"
    if minion.is_file():
        try:
            root = ET.parse(minion).getroot()
            for game in root.findall("./games/game"):
                if game.attrib.get("game-id") != "ESO":
                    continue
                value = game.attrib.get("addon-path")
                if value:
                    candidate = Path(value).expanduser()
                    if candidate.is_dir():
                        return candidate.parent.resolve()
        except (ET.ParseError, OSError):
            pass

    candidates = [
        Path.home() / "Documents" / "Elder Scrolls Online" / "live",
        Path.home() / "OneDrive" / "Documents" / "Elder Scrolls Online" / "live",
        Path.home() / "Documents" / "Elder Scrolls Online" / "liveeu",
    ]
    for candidate in candidates:
        try:
            _child_case_insensitive(candidate, "AddOns")
        except (FileNotFoundError, NotADirectoryError):
            continue
        return candidate.resolve()
    raise FileNotFoundError(
        "ChatMPD could not find ESO's live folder. Choose it in the ESO Add-ons tab."
    )


def resolve_eso_live_directory(value: Path | None) -> Path:
    if value is None:
        return discover_eso_live_directory()
    candidate = Path(value).expanduser()
    if candidate.name.casefold() == "addons":
        candidate = candidate.parent
    if not candidate.is_dir():
        raise FileNotFoundError(f"ESO live folder does not exist: {candidate}")
    _child_case_insensitive(candidate, "AddOns")
    return candidate.resolve()


def format_scan_report(report: EsoScanReport, *, issue_limit: int = 200) -> str:
    """Create a friendly plain-text report for the GUI and command line."""

    lines = [
        "ESO add-on health scan",
        f"Folder: {report.addons_directory}",
        f"Found: {len(report.manifests)} add-on manifests; "
        f"{len(report.enabled_ids)} enabled identifiers",
        f"Result: {report.critical_count} critical, {report.warning_count} warnings, "
        f"{report.repairable_count} safe automatic repairs",
    ]
    if report.current_api is not None:
        lines.append(f"Game add-on API: {report.current_api}")
    if not report.issues:
        lines.extend(["", "No compatibility problems were detected by the local scan."])
        return "\n".join(lines)
    lines.append("")
    ordering = {"critical": 0, "warning": 1, "info": 2}
    issues = sorted(
        report.issues,
        key=lambda item: (ordering[item.severity], item.addon_id.casefold(), item.code),
    )
    for issue in issues[:issue_limit]:
        marker = "FIX AVAILABLE" if issue.repairable else issue.severity.upper()
        lines.append(f"[{marker}] {issue.addon_id}: {issue.message}")
    if len(issues) > issue_limit:
        lines.append(f"... {len(issues) - issue_limit} additional findings omitted")
    return "\n".join(lines)


def format_update_report(updates: Iterable[AddonUpdate]) -> str:
    values = tuple(updates)
    available = [item for item in values if item.update_available]
    lines = [
        "ESOUI update check",
        f"Managed add-ons checked: {len(values)}",
        f"Updates available: {len(available)}",
    ]
    for item in available:
        lines.append(
            f"- {item.name}: {item.installed_version} -> {item.available_version} "
            f"(ESOUI ID {item.uid})"
        )
    if not available:
        lines.append("- Everything tracked is current.")
    return "\n".join(lines)


def _child_case_insensitive(
    parent: Path, name: str, *, required: bool = True
) -> Path:
    direct = parent / name
    if direct.exists():
        return direct
    if parent.is_dir():
        for child in parent.iterdir():
            if child.name.casefold() == name.casefold():
                return child
    if required:
        raise FileNotFoundError(f"Required ESO path is missing: {direct}")
    return direct


def _read_addon_settings(path: Path) -> tuple[dict[str, set[int]], int | None]:
    statuses: dict[str, set[int]] = {}
    current_api: int | None = None
    if not path.is_file():
        return statuses, current_api
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        version = re.fullmatch(r"#Version\s+(\d+)", raw.strip(), re.IGNORECASE)
        if version:
            current_api = int(version.group(1))
            continue
        status = re.fullmatch(r"([^#\s]+)\s+([01])", raw.strip())
        if status:
            statuses.setdefault(status.group(1), set()).add(int(status.group(2)))
    return statuses, current_api


def _scan_manifests(
    addons_root: Path, statuses: dict[str, set[int]]
) -> list[AddonManifest]:
    manifests: list[AddonManifest] = []
    candidates = (
        path
        for path in addons_root.rglob("*")
        if path.suffix.casefold() in {".txt", ".addon"}
    )
    for path in sorted(candidates, key=lambda item: str(item).casefold()):
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > _MANIFEST_LIMIT:
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        fields: dict[str, list[str]] = {}
        payloads: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            match = re.match(r"^##\s*([A-Za-z][A-Za-z0-9_]*)\s*:?\s*(.*)$", line)
            if match:
                fields.setdefault(match.group(1).casefold(), []).append(
                    match.group(2).strip()
                )
                continue
            if not line or line.startswith((";", "#")) or "$(" in line:
                continue
            candidate = line.split(";", 1)[0].strip().replace("\\", "/")
            if candidate.lower().endswith((".lua", ".xml")):
                payloads.append(candidate)
        if "title" not in fields or not any(
            key in fields
            for key in ("apiversion", "dependson", "savedvariables", "islibrary")
        ):
            continue
        relative = path.relative_to(addons_root)
        addon_id = path.stem
        api_versions = tuple(
            int(value)
            for raw in fields.get("apiversion", [])
            for value in re.findall(r"\b\d{6}\b", raw)
        )
        addon_version = _first_integer(fields.get("addonversion", []))
        display_version = _first_value(fields.get("version", []))
        if not display_version and addon_version is not None:
            display_version = str(addon_version)
        missing = tuple(
            payload
            for payload in payloads
            if not (path.parent / Path(payload)).is_file()
        )
        status_values = _status_for(addon_id, statuses)
        manifests.append(
            AddonManifest(
                addon_id=addon_id,
                title=_strip_eso_colors(_first_value(fields["title"]) or addon_id),
                manifest_path=relative.as_posix(),
                package_directory=relative.parts[0],
                api_versions=api_versions,
                addon_version=addon_version,
                display_version=display_version or "unknown",
                dependencies=_parse_dependencies(fields.get("dependson", [])),
                optional_dependencies=_parse_dependencies(
                    fields.get("optionaldependson", [])
                ),
                is_library=(_first_value(fields.get("islibrary", [])).casefold() == "true"),
                enabled=1 in status_values,
                missing_payloads=missing,
            )
        )
    return manifests


def _diagnose(
    addons_root: Path,
    manifests: list[AddonManifest],
    statuses: dict[str, set[int]],
    current_api: int | None,
) -> list[AddonIssue]:
    issues: list[AddonIssue] = []
    by_id: dict[str, list[AddonManifest]] = {}
    for manifest in manifests:
        by_id.setdefault(manifest.addon_id.casefold(), []).append(manifest)
        if manifest.enabled and manifest.missing_payloads:
            preview = ", ".join(manifest.missing_payloads[:3])
            suffix = "" if len(manifest.missing_payloads) <= 3 else " and more"
            issues.append(
                AddonIssue(
                    "missing_payload",
                    "critical",
                    manifest.addon_id,
                    f"manifest references missing files: {preview}{suffix}",
                )
            )
        if manifest.enabled and not manifest.api_versions:
            issues.append(
                AddonIssue(
                    "missing_api", "warning", manifest.addon_id, "manifest has no API version"
                )
            )
        elif (
            manifest.enabled
            and current_api is not None
            and max(manifest.api_versions) < current_api
        ):
            issues.append(
                AddonIssue(
                    "outdated_api",
                    "warning",
                    manifest.addon_id,
                    f"declares API {max(manifest.api_versions)}, older than {current_api}; update it before editing the manifest by hand",
                )
            )

    for copies in by_id.values():
        if len(copies) > 1:
            locations = ", ".join(item.manifest_path for item in copies[:4])
            issues.append(
                AddonIssue(
                    "duplicate_id",
                    "warning",
                    copies[0].addon_id,
                    f"multiple manifests use the same add-on ID: {locations}",
                )
            )

    available = {
        key: max(
            values,
            key=lambda item: item.addon_version if item.addon_version is not None else -1,
        )
        for key, values in by_id.items()
    }
    for manifest in manifests:
        if not manifest.enabled:
            continue
        for dependency in manifest.dependencies:
            installed = available.get(dependency.addon_id.casefold())
            if installed is None:
                issues.append(
                    AddonIssue(
                        "dependency_missing",
                        "critical",
                        manifest.addon_id,
                        f"requires missing {dependency.addon_id}",
                        details=(dependency.addon_id,),
                    )
                )
                continue
            dependency_status = _status_for(dependency.addon_id, statuses)
            if dependency_status and 1 not in dependency_status:
                issues.append(
                    AddonIssue(
                        "dependency_disabled",
                        "critical",
                        manifest.addon_id,
                        f"requires {dependency.addon_id}, but it is disabled",
                        repairable=True,
                        details=(dependency.addon_id,),
                    )
                )
            if (
                dependency.minimum_version is not None
                and installed.addon_version is not None
                and installed.addon_version < dependency.minimum_version
            ):
                issues.append(
                    AddonIssue(
                        "dependency_too_old",
                        "critical",
                        manifest.addon_id,
                        f"requires {dependency.addon_id}>={dependency.minimum_version}, installed {installed.addon_version}",
                    )
                )

    installed_ids = set(by_id)
    for addon_id, values in statuses.items():
        if 1 in values and addon_id.casefold() not in installed_ids:
            issues.append(
                AddonIssue(
                    "orphan_setting",
                    "warning",
                    addon_id,
                    "is enabled in AddOnSettings.txt but no matching manifest was found",
                )
            )

    for directory in sorted(
        (item for item in addons_root.iterdir() if item.is_dir()),
        key=lambda item: item.name.casefold(),
    ):
        if not re.fullmatch(r"\d{9,}-[^\\/]+", directory.name):
            continue
        children = [item for item in directory.iterdir() if item.is_dir()]
        files = [item for item in directory.iterdir() if item.is_file()]
        if len(children) != 1 or files:
            continue
        child = children[0]
        if not any(path.stem.casefold() == child.name.casefold() for path in child.glob("*.txt")):
            continue
        if (addons_root / child.name).exists():
            continue
        issues.append(
            AddonIssue(
                "nested_package",
                "critical",
                child.name,
                f"is nested inside {directory.name}, so ESO may not load it from the expected location",
                repairable=True,
                details=(directory.name, child.name),
            )
        )
    return _deduplicate_issues(issues)


def _parse_dependencies(values: Iterable[str]) -> tuple[Dependency, ...]:
    dependencies: list[Dependency] = []
    for value in values:
        for token in re.split(r"[\s,]+", value.strip()):
            if not token:
                continue
            match = re.fullmatch(r"([^<>=\s]+)(?:>=([0-9]+))?", token)
            if not match:
                continue
            dependencies.append(
                Dependency(
                    match.group(1),
                    int(match.group(2)) if match.group(2) is not None else None,
                )
            )
    return tuple(dependencies)


def _enable_addons_in_settings(path: Path, addon_ids: set[str]) -> None:
    originals = path.read_text(encoding="utf-8-sig", errors="strict").splitlines(
        keepends=True
    )
    wanted = {item.casefold(): item for item in addon_ids}
    found: set[str] = set()
    updated: list[str] = []
    for line in originals:
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        body = line[: -len(ending)] if ending else line
        match = re.fullmatch(r"([^#\s]+)\s+([01])", body.strip())
        if match and match.group(1).casefold() in wanted:
            found.add(match.group(1).casefold())
            updated.append(f"{match.group(1)} 1{ending}")
        else:
            updated.append(line)
    newline = "\r\n" if any(line.endswith("\r\n") for line in originals) else "\n"
    for key, original in wanted.items():
        if key not in found:
            if updated and not updated[-1].endswith(("\r\n", "\n")):
                updated[-1] += newline
            updated.append(f"{original} 1{newline}")
    temporary = path.with_suffix(path.suffix + ".chatmpd-tmp")
    temporary.write_text("".join(updated), encoding="utf-8", newline="")
    os.replace(temporary, path)


def _extract_validated_archive(archive: Path, destination: Path) -> list[str]:
    destination.mkdir(parents=True, exist_ok=False)
    expanded = 0
    top_directories: set[str] = set()
    with zipfile.ZipFile(archive) as package:
        for info in package.infolist():
            normalized = info.filename.replace("\\", "/")
            parts = PurePosixPath(normalized).parts
            if (
                not parts
                or PurePosixPath(normalized).is_absolute()
                or any(part in {"", ".", ".."} for part in parts)
                or ":" in parts[0]
            ):
                raise RuntimeError("The add-on ZIP contains an unsafe path")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise RuntimeError("The add-on ZIP contains a symbolic link")
            expanded += max(info.file_size, 0)
            if expanded > _ARCHIVE_EXPANDED_LIMIT:
                raise RuntimeError("The expanded add-on would exceed 1 GiB")
            if len(parts) > 1 or info.is_dir():
                if _is_safe_directory_name(parts[0]):
                    top_directories.add(parts[0])
                else:
                    raise RuntimeError("The add-on ZIP contains an unsafe directory name")
        package.extractall(destination)
    directories = sorted(
        (name for name in top_directories if (destination / name).is_dir()),
        key=str.casefold,
    )
    if not directories:
        raise RuntimeError("The add-on ZIP contains no installable directory")
    manifest_found = False
    for name in directories:
        for path in (destination / name).rglob("*.txt"):
            if path.stat().st_size > _MANIFEST_LIMIT:
                continue
            header = path.read_text(encoding="utf-8-sig", errors="replace")[:32_768]
            if re.search(r"^##\s*Title\s*:", header, re.MULTILINE | re.IGNORECASE):
                manifest_found = True
                break
        if manifest_found:
            break
    if not manifest_found:
        raise RuntimeError("The add-on ZIP contains no ESO manifest")
    return directories


def _trusted_download_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"cdn.esoui.com", "cdn.mmoui.com"}
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RuntimeError("ESOUI returned an untrusted download address")
    return value


def _read_local_registry(path: Path) -> tuple[ManagedAddon, ...]:
    if not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload.get("addons", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        return ()
    addons: list[ManagedAddon] = []
    for entry in entries:
        try:
            directories = tuple(
                _safe_directory_name(item) for item in entry["directories"]
            )
            addons.append(
                ManagedAddon(
                    int(entry["uid"]),
                    str(entry["name"]),
                    str(entry["installed_version"]),
                    directories,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return tuple(addons)


def _write_local_registry(path: Path, addons: Iterable[ManagedAddon]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": datetime.now(UTC).isoformat(),
        "addons": [
            asdict(addon)
            for addon in sorted(addons, key=lambda item: item.name.casefold())
        ],
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _same_path(left: str | os.PathLike[str], right: Path) -> bool:
    try:
        return Path(left).expanduser().resolve() == right.resolve()
    except (OSError, RuntimeError):
        return False


def _is_minion_running() -> bool:
    try:
        import subprocess

        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Minion.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return any(
        line.strip().casefold().startswith('"minion.exe",')
        for line in completed.stdout.splitlines()
    )


def _status_for(addon_id: str, statuses: dict[str, set[int]]) -> set[int]:
    wanted = addon_id.casefold()
    for key, values in statuses.items():
        if key.casefold() == wanted:
            return values
    return set()


def _first_integer(values: Iterable[str]) -> int | None:
    for value in values:
        match = re.search(r"\d+", value)
        if match:
            return int(match.group())
    return None


def _first_value(values: Iterable[str]) -> str:
    return next((value.strip() for value in values if value.strip()), "")


def _strip_eso_colors(value: str) -> str:
    return re.sub(r"\|c[0-9A-Fa-f]{6}|\|r", "", value).strip()


def _version_key(value: str) -> tuple[tuple[int, int | str], ...]:
    tokens = re.findall(r"\d+|[A-Za-z]+", str(value).casefold())
    return tuple(
        (0, int(token)) if token.isdigit() else (1, token)
        for token in tokens
    )


def _is_safe_directory_name(value: str) -> bool:
    name = str(value).strip()
    return bool(
        name
        and name not in {".", ".."}
        and Path(name).name == name
        and not any(character in name for character in '<>:"/\\|?*')
        and not any(ord(character) < 32 for character in name)
    )


def _safe_directory_name(value: str) -> str:
    name = str(value).strip()
    if not _is_safe_directory_name(name):
        raise ValueError("Unsafe add-on directory name")
    return name


def _deduplicate_issues(issues: Iterable[AddonIssue]) -> list[AddonIssue]:
    result: list[AddonIssue] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        key = (issue.code, issue.addon_id.casefold(), issue.message)
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result

