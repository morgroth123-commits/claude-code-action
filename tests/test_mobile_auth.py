from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.mobile_auth import DeviceCredentialStore


class DeviceCredentialStoreTest(unittest.TestCase):
    def test_pairing_is_one_time_hashed_and_revocable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DeviceCredentialStore(Path(directory))
            code = store.begin_pairing(ttl_seconds=60)
            self.assertRegex(code, r"^\d{6}$")
            with self.assertRaisesRegex(ValueError, "pairing"):
                store.pair("000000", "Phone")

            credential = store.pair(code, "Phone")
            self.assertTrue(store.verify(credential.token))
            self.assertEqual(credential.device_name, "Phone")
            with self.assertRaisesRegex(ValueError, "pairing"):
                store.pair(code, "Second Phone")

            persisted = (Path(directory) / "devices.json").read_text("utf-8")
            self.assertNotIn(credential.token, persisted)
            self.assertNotIn(code, persisted)
            self.assertTrue(store.revoke(credential.device_id))
            self.assertFalse(store.verify(credential.token))


if __name__ == "__main__":
    unittest.main()
