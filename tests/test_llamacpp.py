from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from chatmpd.llamacpp import ChatResponse, LlamaCppProvider, ProviderError, ToolCall


class LocalLlamaServer:
    def __init__(self, responses: dict[tuple[str, str], tuple[int, object]]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str, dict[str, object] | None]] = []
        self.request_headers: list[dict[str, str]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - HTTP method name
                self._respond()

            def do_POST(self) -> None:  # noqa: N802 - HTTP method name
                self._respond()

            def _respond(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                request_body = self.rfile.read(length) if length else b""
                decoded = json.loads(request_body) if request_body else None
                owner.requests.append((self.command, self.path, decoded))
                owner.request_headers.append(dict(self.headers.items()))
                status, body = owner.responses[(self.command, self.path)]
                encoded = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "LocalLlamaServer":
        self._thread.start()
        return self

    def __exit__(self, *unused: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()


class LlamaCppProviderTest(unittest.TestCase):
    def test_refuses_a_non_loopback_endpoint(self) -> None:
        with self.assertRaises(ProviderError):
            LlamaCppProvider(endpoint="http://192.0.2.9:8080")

    def test_refuses_a_loopback_url_with_an_invalid_port(self) -> None:
        with self.assertRaises(ProviderError):
            LlamaCppProvider(endpoint="http://127.0.0.1:not-a-port")

    def test_allows_a_long_local_inference_timeout_without_imposing_a_quota(self) -> None:
        provider = LlamaCppProvider(timeout=180)

        self.assertEqual(provider.timeout, 180)

    def test_health_ignores_proxy_and_api_key_environment_variables(self) -> None:
        environment_values = {
            name: os.environ.get(name)
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "OPENAI_API_KEY")
        }
        try:
            os.environ.update(
                {
                    "HTTP_PROXY": "http://127.0.0.1:1",
                    "HTTPS_PROXY": "http://127.0.0.1:1",
                    "ALL_PROXY": "http://127.0.0.1:1",
                    "NO_PROXY": "",
                    "OPENAI_API_KEY": "must-not-be-sent",
                }
            )
            with LocalLlamaServer(
                {("GET", "/health"): (200, {"status": "ok"})}
            ) as server:
                self.assertTrue(LlamaCppProvider(endpoint=server.endpoint).health())
        finally:
            for name, value in environment_values.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        headers = {name.lower(): value for name, value in server.request_headers[0].items()}
        self.assertNotIn("authorization", headers)
        self.assertNotIn("x-api-key", headers)

    def test_health_requests_the_local_readiness_endpoint(self) -> None:
        with LocalLlamaServer({("GET", "/health"): (200, {"status": "ok"})}) as server:
            provider = LlamaCppProvider(endpoint=server.endpoint)

            self.assertTrue(provider.health())

        self.assertEqual(server.requests, [("GET", "/health", None)])

    def test_models_returns_ids_from_the_openai_models_endpoint(self) -> None:
        with LocalLlamaServer(
            {
                ("GET", "/v1/models"): (
                    200,
                    {
                        "object": "list",
                        "data": [
                            {"id": "chatmpd-local", "object": "model"},
                            {"id": "another-local-model", "object": "model"},
                        ],
                    },
                )
            }
        ) as server:
            provider = LlamaCppProvider(endpoint=server.endpoint)

            self.assertEqual(
                provider.models(), ("chatmpd-local", "another-local-model")
            )

        self.assertEqual(server.requests, [("GET", "/v1/models", None)])

    def test_chat_sends_a_non_streaming_tool_request_and_normalizes_a_call(self) -> None:
        tool_schema = {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file from the workspace.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["path"],
                    "properties": {"path": {"type": "string"}},
                },
            },
        }
        response_body = {
            "id": "chatcmpl-local",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_6789",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path":"README.md"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
        with LocalLlamaServer(
            {("POST", "/v1/chat/completions"): (200, response_body)}
        ) as server:
            provider = LlamaCppProvider(endpoint=server.endpoint)

            response = provider.chat(
                messages=[{"role": "user", "content": "Read the project instructions."}],
                tools=[tool_schema],
                tool_choice="auto",
            )

        self.assertEqual(
            response,
            ChatResponse(
                text="",
                tool_calls=(
                    ToolCall(
                        id="call_6789",
                        name="read_file",
                        arguments={"path": "README.md"},
                    ),
                ),
                finish_reason="tool_calls",
            ),
        )
        self.assertEqual(
            server.requests,
            [
                (
                    "POST",
                    "/v1/chat/completions",
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": "Read the project instructions.",
                            }
                        ],
                        "tools": [tool_schema],
                        "tool_choice": "auto",
                        "stream": False,
                        "temperature": 0,
                        "parallel_tool_calls": False,
                    },
                )
            ],
        )

    def test_chat_accepts_object_valued_native_tool_arguments(self) -> None:
        response_body = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "I will inspect the file.",
                        "tool_calls": [
                            {
                                "id": "call_object",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": {"path": "src/main.py"},
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool",
                }
            ]
        }
        with LocalLlamaServer(
            {("POST", "/v1/chat/completions"): (200, response_body)}
        ) as server:
            response = LlamaCppProvider(endpoint=server.endpoint).chat(
                messages=[{"role": "user", "content": "Inspect the project."}]
            )

        self.assertEqual(response.text, "I will inspect the file.")
        self.assertEqual(
            response.tool_calls,
            (
                ToolCall(
                    id="call_object",
                    name="read_file",
                    arguments={"path": "src/main.py"},
                ),
            ),
        )
        self.assertEqual(response.finish_reason, "tool")

    def test_chat_rejects_malformed_tool_arguments_without_exposing_response_body(self) -> None:
        response_body = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_bad",
                                "function": {
                                    "name": "read_file",
                                    "arguments": "not-json-secret-token",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        with LocalLlamaServer(
            {("POST", "/v1/chat/completions"): (200, response_body)}
        ) as server:
            with self.assertRaisesRegex(ProviderError, "invalid tool arguments") as raised:
                LlamaCppProvider(endpoint=server.endpoint).chat(
                    messages=[{"role": "user", "content": "Read a file."}]
                )

        self.assertNotIn("not-json-secret-token", str(raised.exception))

    def test_chat_rejects_non_standard_json_constants_in_tool_arguments(self) -> None:
        response_body = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_nonfinite",
                                "function": {
                                    "name": "read_file",
                                    "arguments": {"path": float("nan")},
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
        with LocalLlamaServer(
            {("POST", "/v1/chat/completions"): (200, response_body)}
        ) as server:
            with self.assertRaises(ProviderError):
                LlamaCppProvider(endpoint=server.endpoint).chat(
                    messages=[{"role": "user", "content": "Read a file."}]
                )


if __name__ == "__main__":
    unittest.main()
