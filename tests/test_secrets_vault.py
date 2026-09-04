from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.platform_db import PlatformDatabase
from chatmpd.secrets_vault import SecretsVault


class _Cipher:
    def protect(self, data: bytes) -> bytes:
        return b"cipher:" + data[::-1]

    def unprotect(self, data: bytes) -> bytes:
        self_prefix = b"cipher:"
        if not data.startswith(self_prefix):
            raise ValueError("bad ciphertext")
        return data[len(self_prefix):][::-1]


class SecretsVaultTest(unittest.TestCase):
    def test_ciphertext_at_rest_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "db.sqlite"
            db = PlatformDatabase(path)
            vault = SecretsVault(db, cipher=_Cipher())
            vault.set("nexus-api", "super-secret-key")
            with db.connect() as connection:
                raw = str(connection.execute(
                    "SELECT payload FROM platform_records WHERE namespace='secret'"
                ).fetchone()["payload"])
            self.assertNotIn("super-secret-key", raw)
            restarted = SecretsVault(PlatformDatabase(path), cipher=_Cipher())
            self.assertEqual(restarted.get("nexus-api"), "super-secret-key")
            self.assertIn("nexus-api", restarted.names())
            self.assertTrue(restarted.delete("nexus-api"))


if __name__ == "__main__":
    unittest.main()
