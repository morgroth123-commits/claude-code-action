# llama.cpp provider implementation report

`chatmpd.llamacpp.LlamaCppProvider` is a standard-library-only adapter for a
locally started llama.cpp server.

## Supported operations

- `health()` requests `GET /health` and succeeds only for `{"status":"ok"}`.
- `models()` requests `GET /v1/models` and returns the advertised model IDs.
- `chat(messages, tools=None, tool_choice=None)` requests
  `POST /v1/chat/completions` with non-streaming generation, temperature zero,
  and `parallel_tool_calls: false`. It preserves assistant text and normalizes
  zero or more native calls into `{id, name, arguments}` values.

Tool arguments may be supplied by llama.cpp as a JSON string or as an already
decoded JSON object. Invalid response structures, invalid tool arguments, and
non-standard JSON constants are rejected with safe provider errors.

## Local-only safeguards

- Only `http://127.0.0.1`, `http://localhost`, and `http://[::1]` base URLs
  are accepted. Credentials, paths, query strings, fragments, non-HTTP
  schemes, remote hosts, and invalid ports are rejected.
- Requests use an explicit empty proxy configuration, so proxy environment
  variables are ignored.
- The provider accepts no API-key setting and sends no authorization header.
- Requests use a configurable bounded timeout (default: 10 seconds; maximum:
  60 seconds) and both request and response bodies are limited to 1 MiB.
- Server and protocol failures expose generic operational messages rather than
  response bodies.

## Verification

Tests use an in-process `ThreadingHTTPServer`; no llama.cpp process or model
was started. The focused provider suite passed with 9 tests, and full unittest
discovery passed with 23 tests:

```text
.venv\\Scripts\\python.exe -m unittest tests.test_llamacpp -v
.venv\\Scripts\\python.exe -m unittest discover -s tests -v
```

## Current scope

This adapter intentionally does not start servers, download models, read model
credentials, or execute tools. The caller remains responsible for choosing a
locally installed model and validating/executing any normalized tool call.
