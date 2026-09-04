from __future__ import annotations

import unittest

from chatmpd.host_policy import HostAction, HostActionPolicy


class HostActionPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = HostActionPolicy()

    def test_normal_work_is_autonomous(self) -> None:
        for action in (
            HostAction("file", "write", r"C:\Users\Owner\Documents\notes.txt"),
            HostAction("application", "install", "ComfyUI"),
            HostAction("process", "diagnose", "python.exe"),
            HostAction("configuration", "edit", "Vortex profile"),
        ):
            with self.subTest(action=action):
                decision = self.policy.evaluate(action)
                self.assertFalse(decision.requires_confirmation)
                self.assertEqual(decision.level, "autonomous")

    def test_critical_system_actions_require_confirmation(self) -> None:
        for action in (
            HostAction("security", "disable", "Windows Defender"),
            HostAction("disk", "format", "D:"),
            HostAction("firmware", "update", "UEFI"),
            HostAction("credentials", "export", "browser passwords"),
        ):
            with self.subTest(action=action):
                decision = self.policy.evaluate(action)
                self.assertTrue(decision.requires_confirmation)
                self.assertEqual(decision.level, "critical")

    def test_destructive_system_targets_are_critical_even_for_generic_file_actions(self) -> None:
        decision = self.policy.evaluate(
            HostAction("file", "delete", r"C:\Windows\System32")
        )
        self.assertTrue(decision.requires_confirmation)
        self.assertEqual(decision.level, "critical")


if __name__ == "__main__":
    unittest.main()
