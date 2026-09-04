"""Sanitized portable ChatMPD pack export."""

from __future__ import annotations

import json
import tomllib
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


class PackExporter:
    _PRIVATE_PARTS = {
        "conversations", "memory", "memories", "credentials", "secrets",
        "tokens", "auth", "device-auth", "recovery", "private",
    }
    _EXPLICIT_CATEGORIES = {"explicit_sex", "explicit-sex", "pornography"}

    def create_pack(
        self,
        destination: Path,
        *,
        include_paths: Iterable[Path],
        metadata: Mapping[str, Any] | None = None,
    ) -> Path:
        target = Path(destination).expanduser().resolve()
        if target.suffix.casefold() != ".chatmpdpack":
            raise ValueError("ChatMPD packs must use the .chatmpdpack extension.")
        roots = [Path(item).expanduser().resolve() for item in include_paths]
        if not roots:
            raise ValueError("At least one explicit include path is required.")

        files: list[tuple[Path, str]] = []
        for root in roots:
            self._validate_root(root)
            if root.is_file():
                files.append((root, f"files/{root.name}"))
                continue
            for path in sorted(root.rglob("*")):
                if path.is_symlink():
                    raise ValueError(f"Pack include cannot contain symlinks: {path}")
                if not path.is_file():
                    continue
                relative = path.relative_to(root).as_posix()
                files.append((path, f"extensions/{root.name}/{relative}"))
        manifest = {
            "format": "chatmpdpack",
            "version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "metadata": dict(metadata or {}),
            "policy": {
                "private_state_included": False,
                "explicit_sex_extensions_allowed": False,
            },
            "files": [archive_name for _path, archive_name in files],
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        if temporary.exists():
            temporary.unlink()
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2, ensure_ascii=False),
            )
            for source, archive_name in files:
                archive.write(source, archive_name)
        temporary.replace(target)
        return target

    def _validate_root(self, root: Path) -> None:
        if not root.exists():
            raise FileNotFoundError(root)
        if any(part.casefold() in self._PRIVATE_PARTS for part in root.parts):
            raise ValueError(f"Pack include contains private ChatMPD state: {root}")
        manifest = root / "chatmpd-extension.toml" if root.is_dir() else None
        if manifest is not None and manifest.is_file():
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
            categories = {
                str(item).strip().casefold()
                for item in data.get("content_categories", [])
            }
            if categories & self._EXPLICIT_CATEGORIES:
                raise ValueError("explicit sexual-content extensions are excluded from shareable ChatMPD packs.")
