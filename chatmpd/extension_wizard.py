"""Create portable ChatMPD skill and subprocess-plugin skeletons."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .platform_paths import PlatformPaths


_EXPLICIT = {"explicit_sex", "explicit-sex", "pornography"}
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,119}$")


class ExtensionWizard:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root or PlatformPaths.default().extensions)

    def create_skill(
        self,
        name: str,
        *,
        capability_id: str,
        description: str = "",
        content_categories: Iterable[str] = (),
    ) -> Path:
        clean_id = self._validate(capability_id, content_categories)
        clean_name = " ".join(str(name).split()).strip()
        if not clean_name:
            raise ValueError("Skill name is required.")
        folder = self._folder(clean_id)
        categories = [str(item).strip() for item in content_categories if str(item).strip()]
        manifest = [
            "[extension]",
            f'id = "{clean_id}"',
            f'name = "{clean_name.replace(chr(34), chr(39))}"',
            'kind = "skill"',
            'version = "1"',
            'risk = "safe"',
            'entrypoint = "SKILL.md"',
            f'description = "{str(description).strip().replace(chr(34), chr(39))}"',
        ]
        if categories:
            values = ", ".join(f'"{item}"' for item in categories)
            manifest.append(f"content_categories = [{values}]")
        (folder / "skill.toml").write_text("\n".join(manifest) + "\n", encoding="utf-8")
        (folder / "SKILL.md").write_text(
            f"# {clean_name}\n\n## Purpose\n{str(description).strip() or 'Describe what this skill should accomplish.'}\n\n"
            "## Instructions\nUse the capability only when it directly helps the user's request. "
            "Preserve ChatMPD permission and verification boundaries.\n",
            encoding="utf-8",
        )
        return folder

    def create_plugin(self, name: str, *, capability_id: str, description: str = "") -> Path:
        clean_id = self._validate(capability_id, ())
        clean_name = " ".join(str(name).split()).strip()
        folder = self._folder(clean_id)
        manifest = (
            "[extension]\n"
            f'id = "{clean_id}"\n'
            f'name = "{clean_name.replace(chr(34), chr(39))}"\n'
            'kind = "plugin"\nversion = "1"\nrisk = "safe"\n'
            'entrypoint = "plugin.py"\ncommand = ["python", "plugin.py"]\n'
            f'description = "{str(description).strip().replace(chr(34), chr(39))}"\n'
        )
        (folder / "skill.toml").write_text(manifest, encoding="utf-8")
        (folder / "plugin.py").write_text(
            "import json, sys\n"
            "payload = json.loads(sys.stdin.read() or '{}')\n"
            "print(json.dumps({'status':'ready','echo':payload}))\n",
            encoding="utf-8",
        )
        return folder

    def _folder(self, clean_id: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        folder = self.root / clean_id
        if folder.exists():
            raise FileExistsError(folder)
        folder.mkdir()
        return folder

    @staticmethod
    def _validate(capability_id: str, categories: Iterable[str]) -> str:
        clean_id = str(capability_id).strip().casefold()
        if not _ID_PATTERN.fullmatch(clean_id):
            raise ValueError("Capability id must use lowercase letters, numbers, dot, dash, or underscore.")
        normalized = {str(item).strip().casefold() for item in categories}
        if normalized & _EXPLICIT:
            raise ValueError("explicit sexual-content extension categories are not supported by the sharing framework.")
        return clean_id
