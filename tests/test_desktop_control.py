from __future__ import annotations

import unittest

from chatmpd.desktop_control import DesktopController
from chatmpd.host_policy import HostDecision


class _Policy:
    def __init__(self, confirm: bool) -> None:
        self.confirm = confirm
    def evaluate(self, _action):
        return HostDecision("test", self.confirm, "test policy")


class _Backend:
    def __init__(self) -> None:
        self.calls = []
    def click(self, x: int, y: int) -> None:
        self.calls.append(("click", x, y))
    def type_text(self, text: str) -> None:
        self.calls.append(("type", text))


class DesktopControllerTest(unittest.TestCase):
    def test_disabled_by_default_and_confirmation_gate(self) -> None:
        backend = _Backend()
        controller = DesktopController(policy=_Policy(False), backend=backend)
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            controller.click(10, 20)
        controller.set_enabled(True)
        controller.click(10, 20)
        self.assertEqual(backend.calls[-1], ("click", 10, 20))

        guarded = DesktopController(policy=_Policy(True), backend=backend, enabled=True)
        with self.assertRaises(PermissionError):
            guarded.type_text("hello")
        guarded.type_text("hello", confirmed=True)
        self.assertEqual(backend.calls[-1], ("type", "hello"))


if __name__ == "__main__":
    unittest.main()
