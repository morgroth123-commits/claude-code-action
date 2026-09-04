from __future__ import annotations

import unittest

from chatmpd.hardware import HardwareProfile, recommend_model_tier


class HardwareProfileTest(unittest.TestCase):
    def test_recommends_tier_from_vram_and_ram(self) -> None:
        small = HardwareProfile("Windows", 8, 12.0, "GPU", 4.0)
        medium = HardwareProfile("Windows", 12, 32.0, "GPU", 12.0)
        large = HardwareProfile("Windows", 16, 64.0, "GPU", 24.0)
        self.assertEqual(recommend_model_tier(small), "small")
        self.assertEqual(recommend_model_tier(medium), "medium")
        self.assertEqual(recommend_model_tier(large), "large")

    def test_summary_is_shareable_and_contains_no_machine_secrets(self) -> None:
        profile = HardwareProfile("Windows 11", 6, 31.9, "RTX 3060", 12.0)
        payload = profile.as_dict()
        self.assertEqual(payload["gpu_vram_gib"], 12.0)
        self.assertNotIn("username", payload)
        self.assertNotIn("hostname", payload)


if __name__ == "__main__":
    unittest.main()
