from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.conversation_library import ConversationLibrary


class ConversationWorkspaceTest(unittest.TestCase):
    def test_workspace_persists_and_branch_inherits_it(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            library = ConversationLibrary(Path(folder))
            document = library.create()
            updated = library.set_workspace(document.conversation_id, r"C:\Projects\GameMod")
            self.assertEqual(updated.workspace, r"C:\Projects\GameMod")

            restarted = ConversationLibrary(Path(folder))
            loaded = restarted.load(document.conversation_id)
            self.assertEqual(loaded.workspace, r"C:\Projects\GameMod")
            branch = restarted.branch(document.conversation_id)
            self.assertEqual(branch.workspace, r"C:\Projects\GameMod")

    def test_workspace_can_be_cleared_without_touching_messages(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            library = ConversationLibrary(Path(folder))
            document = library.create([{"role": "user", "content": "Keep me"}])
            library.set_workspace(document.conversation_id, r"C:\Repo")
            cleared = library.set_workspace(document.conversation_id, None)
            self.assertIsNone(cleared.workspace)
            self.assertEqual(cleared.messages[0]["content"], "Keep me")
