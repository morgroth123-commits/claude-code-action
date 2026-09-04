from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "chatmpd" / "web"


class WebAssetTest(unittest.TestCase):
    def test_html_has_modern_llm_landmarks_and_controls(self) -> None:
        page = (WEB / "index.html").read_text(encoding="utf-8")
        for required in (
            'id="sidebar"', 'id="new-chat"', 'id="conversation-search"',
            'id="conversation-list"', 'id="transcript"', 'id="composer"',
            'id="prompt"', 'id="send"', 'id="artifact-pane"',
            'id="mobile-dialog"', 'id="mobile-pair-screen"', 'aria-live="polite"',
        ):
            self.assertIn(required, page)
        self.assertIn("ChatMPD", page)
        self.assertIn("chatmpd-192.png", page)

    def test_css_supports_system_theme_accessibility_and_mobile_layout(self) -> None:
        css = (WEB / "app.css").read_text(encoding="utf-8")
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("@media (max-width: 820px)", css)
        self.assertIn("--accent", css)
        self.assertIn(".composer-shell", css)

    def test_javascript_uses_safe_dom_rendering_and_expected_interactions(self) -> None:
        script = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("textContent", script)
        self.assertNotIn("innerHTML", script)
        for required in (
            "loadConversations", "openConversation", "createConversation",
            "renameConversation", "togglePin", "branchConversation",
            "deleteConversation", "submitPrompt", "cancelActiveJob",
            "renderRichText", "copyText", "setTheme", "pairDevice",
        ):
            self.assertIn(required, script)
        self.assertIn("event.shiftKey", script)
        self.assertIn("event.key === 'Enter'", script)
        self.assertIn("URLSearchParams", script)
        self.assertIn("chatmpd-mobile-token", script)


if __name__ == "__main__":
    unittest.main()
