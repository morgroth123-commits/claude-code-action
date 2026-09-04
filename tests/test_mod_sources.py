from __future__ import annotations

import unittest

from chatmpd.mod_sources import EsoUiCatalog, NexusModsCatalog


class ModSourceTest(unittest.TestCase):
    def test_esoui_uses_public_catalog_not_private_minion_api(self) -> None:
        source = EsoUiCatalog()
        self.assertEqual(source.catalog_url, "https://www.esoui.com/addons.php")
        self.assertIn("esoui.com/downloads/info", source.addon_page(73))
        self.assertNotIn("api.mmoui.com", source.addon_page(73))

    def test_nexus_public_trending_and_optional_keyed_details(self) -> None:
        calls = []
        def opener(url: str, headers: dict[str, str]):
            calls.append((url, headers))
            return {"data": [{"name": "Useful Mod", "adult": False}]}

        source = NexusModsCatalog(opener=opener)
        result = source.trending("skyrimspecialedition")
        self.assertEqual(result[0]["name"], "Useful Mod")
        self.assertEqual(calls[0][1], {})
        with self.assertRaisesRegex(ValueError, "API key"):
            source.mod_details("skyrimspecialedition", "12604")

        keyed = NexusModsCatalog(api_key_provider=lambda: "abc", opener=opener)
        keyed.mod_details("skyrimspecialedition", "12604")
        self.assertEqual(calls[-1][1].get("apikey"), "abc")


if __name__ == "__main__":
    unittest.main()
