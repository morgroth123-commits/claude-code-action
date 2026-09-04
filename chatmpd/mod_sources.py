"""Canonical public repository sources for ESOUI/Minion and Nexus/Vortex."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen


JsonOpener = Callable[[str, dict[str, str]], Mapping[str, Any]]


class EsoUiCatalog:
    """Public ESOUI catalog references; never calls Minion's private MMOUI API."""

    catalog_url = "https://www.esoui.com/addons.php"
    search_url = "https://www.esoui.com/downloads/search.php"

    @staticmethod
    def addon_page(addon_id: int | str) -> str:
        value = str(addon_id).strip()
        if not value.isdigit() or int(value) <= 0:
            raise ValueError("ESOUI addon id must be a positive integer.")
        return f"https://www.esoui.com/downloads/info{int(value)}.html"

    @staticmethod
    def policy() -> dict[str, Any]:
        return {
            "catalog": EsoUiCatalog.catalog_url,
            "installed_metadata": "Minion local state",
            "private_minion_api_used": False,
        }


class NexusModsCatalog:
    """Official Nexus Mods API adapter with optional personal key support."""

    api_root = "https://api.nexusmods.com/v3"
    site_root = "https://www.nexusmods.com"

    def __init__(
        self,
        *,
        api_key_provider: Callable[[], str] | None = None,
        opener: JsonOpener | None = None,
    ) -> None:
        self.api_key_provider = api_key_provider
        self.opener = opener or self._open_json

    def trending(self, game_domain: str) -> list[dict[str, Any]]:
        game = self._game(game_domain)
        payload = self.opener(f"{self.api_root}/games/{game}/trending-mods", {})
        data = payload.get("data", [])
        if isinstance(data, dict):
            values = data.get("mods") or data.get("items") or []
        else:
            values = data
        if not isinstance(values, list):
            raise RuntimeError("Nexus Mods returned an unexpected trending response.")
        return [dict(item) for item in values if isinstance(item, Mapping)]

    def mod_details(self, game_domain: str, mod_id: int | str) -> dict[str, Any]:
        if self.api_key_provider is None:
            raise ValueError("A Nexus Mods API key is required for this authenticated request.")
        key = str(self.api_key_provider() or "").strip()
        if not key:
            raise ValueError("A Nexus Mods API key is required for this authenticated request.")
        game = self._game(game_domain)
        value = str(mod_id).strip()
        if not value.isdigit() or int(value) <= 0:
            raise ValueError("Nexus mod id must be a positive integer.")
        payload = self.opener(
            f"{self.api_root}/games/{game}/mods/{int(value)}",
            {"apikey": key},
        )
        data = payload.get("data", payload)
        if isinstance(data, list) and len(data) == 1 and isinstance(data[0], Mapping):
            data = data[0]
        if not isinstance(data, Mapping):
            raise RuntimeError("Nexus Mods returned an unexpected mod response.")
        return dict(data)

    @staticmethod
    def mod_page(game_domain: str, mod_id: int | str) -> str:
        game = NexusModsCatalog._game(game_domain)
        value = str(mod_id).strip()
        if not value.isdigit() or int(value) <= 0:
            raise ValueError("Nexus mod id must be a positive integer.")
        return f"https://www.nexusmods.com/{game}/mods/{int(value)}"

    @staticmethod
    def _game(value: str) -> str:
        game = str(value).strip().casefold()
        if not game or not all(character.isalnum() or character in "-_" for character in game):
            raise ValueError("Invalid Nexus Mods game domain.")
        return game

    @staticmethod
    def _open_json(url: str, headers: dict[str, str]) -> Mapping[str, Any]:
        request = Request(
            url,
            headers={"User-Agent": "ChatMPD/0.3", "Accept": "application/json", **headers},
            method="GET",
        )
        with urlopen(request, timeout=20) as response:
            if int(getattr(response, "status", 200)) >= 400:
                raise RuntimeError(f"Repository request failed: HTTP {response.status}")
            payload = json.loads(response.read(4 * 1024 * 1024 + 1).decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise RuntimeError("Repository response must be a JSON object.")
        return payload
