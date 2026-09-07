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
            'id="attachment-button"', 'id="attachment-input"', 'id="attachment-list"',
            'id="welcome-suggestions"',
        ):
            self.assertIn(required, page)
        self.assertIn("ChatMPD", page)
        self.assertIn("chatmpd-192.png", page)
        self.assertIn("Settings", page)
        self.assertIn("Help me with this PC", page)
        self.assertIn("Work on a project", page)
        self.assertNotIn(">Control Center<", page)

    def test_css_supports_system_theme_accessibility_and_mobile_layout(self) -> None:
        css = (WEB / "app.css").read_text(encoding="utf-8")
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("@media (max-width: 820px)", css)
        self.assertIn("--accent", css)
        self.assertIn(".composer-shell", css)
        self.assertRegex(css, r"\[hidden\]\s*\{[^}]*display\s*:\s*none\s*!important")

    def test_javascript_uses_safe_dom_rendering_and_expected_interactions(self) -> None:
        script = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("textContent", script)
        self.assertNotIn("innerHTML", script)
        for required in (
            "loadConversations", "openConversation", "createConversation",
            "renameConversation", "togglePin", "branchConversation",
            "deleteConversation", "submitPrompt", "cancelActiveJob",
            "renderRichText", "copyText", "setTheme", "pairDevice",
            "uploadAttachments", "renderAttachmentChips", "renderSuggestedAction",
            "renderConfirmation", "chooseWorkspace", "dragover", "drop",
        ):
            self.assertIn(required, script)
        self.assertIn("event.shiftKey", script)
        self.assertIn("event.key === 'Enter'", script)
        self.assertIn("URLSearchParams", script)
        self.assertIn("chatmpd-mobile-token", script)
        self.assertIn("attachment_ids", script)
        self.assertIn("needs_context", script)
        self.assertIn("status_label", script)
        # Everyday labels stay plain-language; capability ids are not primary UI copy.
        self.assertNotRegex(script, r'textContent\s*=\s*["\']capability["\']')


if __name__ == "__main__":
    unittest.main()


class ProjectContinuityWebAssetTest(unittest.TestCase):
    def test_project_picker_is_native_and_workspace_is_restored_per_conversation(self) -> None:
        script = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/system/select-folder", script)
        self.assertIn("/workspace", script)
        self.assertIn("document.workspace", script)
        self.assertNotIn('window.prompt("Project folder on this PC"', script)


class AssistantFirstWebAssetTest(unittest.TestCase):
    def test_composer_and_welcome_have_nontechnical_assistant_controls(self) -> None:
        page = (WEB / "index.html").read_text(encoding="utf-8")
        for required in (
            'id="attachment-button"', 'id="attachment-input"',
            'id="attachment-list"', 'id="welcome-suggestions"',
            'data-suggestion=', 'id="advanced-settings"',
        ):
            self.assertIn(required, page)
        self.assertIn(">Settings<", page)
        self.assertIn("Advanced", page)
        self.assertNotIn(">Control Center<", page)

    def test_javascript_wires_attachments_guided_actions_and_retry(self) -> None:
        script = (WEB / "app.js").read_text(encoding="utf-8")
        for required in (
            "uploadAttachments", "renderAttachmentChips", "removeAttachment",
            "renderSuggestedAction", "renderConfirmation", "retryLastRequest",
            "pendingAttachmentIds", "attachment_ids", "dragover", "drop",
        ):
            self.assertIn(required, script)
        self.assertIn("choose_workspace", script)
        self.assertNotIn("innerHTML", script)

    def test_css_styles_progressive_disclosure_and_attachment_flow(self) -> None:
        css = (WEB / "app.css").read_text(encoding="utf-8")
        for required in (
            ".attachment-list", ".attachment-chip", ".welcome-suggestions",
            ".suggestion-button", ".inline-action-card", ".advanced-settings",
        ):
            self.assertIn(required, css)
