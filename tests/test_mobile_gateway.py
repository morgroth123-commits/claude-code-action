from __future__ import annotations

import http.client
import json
import tempfile
import unittest
from pathlib import Path

from chatmpd.mobile_auth import DeviceCredentialStore
from chatmpd.mobile_gateway import GatewayConfig, MobileGateway


class MobileGatewayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.calls: list[tuple[str, str | None]] = []
        credentials = DeviceCredentialStore(Path(self.temporary.name) / "auth")
        self.gateway = MobileGateway(
            command_handler=self._command,
            credential_store=credentials,
            status_handler=lambda: {"mode": "ready"},
            config=GatewayConfig(host="127.0.0.1", port=0, max_body_bytes=4096),
        )
        self.gateway.start()

    def tearDown(self) -> None:
        self.gateway.stop()
        self.temporary.cleanup()

    def _command(self, text: str, workspace: str | None = None) -> dict[str, str]:
        self.calls.append((text, workspace))
        return {"answer": f"done: {text}"}
    def _request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        token: str | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        connection = http.client.HTTPConnection("127.0.0.1", self.gateway.port, timeout=3)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        connection.close()
        return response.status, data, response_headers

    def _pair(self) -> str:
        code = self.gateway.begin_pairing()
        status, body, _headers = self._request(
            "POST", "/api/pair", {"code": code, "device_name": "Test phone"}
        )
        self.assertEqual(status, 200)
        return json.loads(body)["token"]
    def test_pairing_then_authenticated_command_and_status(self) -> None:
        unauthorized, _body, _headers = self._request(
            "POST", "/api/command", {"text": "hello"}
        )
        self.assertEqual(unauthorized, 401)

        token = self._pair()
        status, body, headers = self._request(
            "POST",
            "/api/command",
            {"text": "hello", "workspace": "C:/project"},
            token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["answer"], "done: hello")
        self.assertEqual(self.calls, [("hello", "C:/project")])
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")

        status, body, _headers = self._request("GET", "/api/status", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"mode": "ready"})

    def test_exposes_public_mobile_client_mode_before_pairing(self) -> None:
        status, body, _headers = self._request("GET", "/api/client")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["mode"], "mobile")

    def test_serves_installable_pwa_shell_and_manifest(self) -> None:
        status, body, _headers = self._request("GET", "/")
        self.assertEqual(status, 200)
        page = body.decode("utf-8")
        self.assertIn("ChatMPD", page)
        self.assertIn("manifest.webmanifest", page)
        self.assertIn("/api/command", page)

        status, body, _headers = self._request("GET", "/manifest.webmanifest")
        self.assertEqual(status, 200)
        manifest = json.loads(body)
        self.assertEqual(manifest["name"], "ChatMPD")
        self.assertTrue(any(icon["sizes"] == "192x192" for icon in manifest["icons"]))
        self.assertTrue(any(icon["sizes"] == "512x512" for icon in manifest["icons"]))


if __name__ == "__main__":
    unittest.main()
