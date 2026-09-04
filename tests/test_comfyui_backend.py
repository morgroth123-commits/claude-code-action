from __future__ import annotations

import unittest

from chatmpd.comfyui import ComfyUIBackend, ComfyUIClient
from chatmpd.media import normalize_media_request


class _SequenceTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if not self.responses:
            raise AssertionError("unexpected ComfyUI request")
        return self.responses.pop(0)


class ComfyUIClientTest(unittest.TestCase):
    def test_rejects_non_loopback_endpoint_by_default(self) -> None:
        with self.assertRaisesRegex(ValueError, "loopback"):
            ComfyUIClient("http://192.168.1.50:8188")

    def test_submit_uses_native_prompt_api(self) -> None:
        transport = _SequenceTransport([{"prompt_id": "job-1"}])
        client = ComfyUIClient(
            "http://127.0.0.1:8188", request_json=transport
        )
        job_id = client.submit({"1": {"class_type": "Example", "inputs": {}}})
        self.assertEqual(job_id, "job-1")
        self.assertEqual(
            transport.calls,
            [("POST", "/prompt", {"prompt": {"1": {"class_type": "Example", "inputs": {}}}})],
        )

    def test_backend_waits_for_history_and_returns_outputs(self) -> None:
        transport = _SequenceTransport([
            {"prompt_id": "job-2"},
            {},
            {
                "job-2": {
                    "status": {"status_str": "success", "completed": True},
                    "outputs": {"9": {"images": [{"filename": "result.png"}]}},
                }
            },
        ])
        client = ComfyUIClient(
            "http://127.0.0.1:8188", request_json=transport, sleep=lambda _: None
        )
        backend = ComfyUIBackend(
            client,
            workflow_builder=lambda plan: {
                "1": {"class_type": "Prompt", "inputs": {"text": plan.prompt}}
            },
            poll_interval=0,
            completion_timeout=10,
        )
        result = backend.generate(normalize_media_request("Create a sensual image"))
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.job_id, "job-2")
        self.assertEqual(result.outputs["9"]["images"][0]["filename"], "result.png")


if __name__ == "__main__":
    unittest.main()
