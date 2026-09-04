from __future__ import annotations

import unittest

from chatmpd.router import RequestRouter


class RequestRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.router = RequestRouter()

    def test_routes_media_requests_without_exposing_backend(self) -> None:
        decision = self.router.classify(
            "Create a 20 minute realistic fictional adult sensual compilation"
        )
        self.assertEqual(decision.capability, "media")
        self.assertFalse(decision.requires_workspace)

    def test_routes_eso_before_generic_system_or_modding_terms(self) -> None:
        decision = self.router.classify(
            "Fix my ESO addon conflicts and keep HarvestMap working"
        )
        self.assertEqual(decision.capability, "eso")
        self.assertFalse(decision.requires_workspace)

    def test_routes_vortex_and_general_mod_management(self) -> None:
        decision = self.router.classify("Check my Vortex deployment conflicts")
        self.assertEqual(decision.capability, "vortex")

    def test_routes_project_code_work_when_workspace_is_implied(self) -> None:
        decision = self.router.classify("Fix the failing tests in this project")
        self.assertEqual(decision.capability, "coding")
        self.assertTrue(decision.requires_workspace)

    def test_routes_host_work_and_falls_back_to_chat(self) -> None:
        system = self.router.classify("Diagnose why Windows audio is crackling")
        chat = self.router.classify("Explain photosynthesis simply")
        self.assertEqual(system.capability, "system")
        self.assertEqual(chat.capability, "chat")

    def test_handler_dispatch_keeps_one_plain_language_front_door(self) -> None:
        calls = []
        router = RequestRouter(
            handlers={"media": lambda text, **context: calls.append((text, context)) or "ok"}
        )
        result = router.dispatch("Create a 30 second sensual video")
        self.assertEqual(result, "ok")
        self.assertEqual(calls[0][0], "Create a 30 second sensual video")


if __name__ == "__main__":
    unittest.main()
