# ChatMPD Mobile Gateway Design

**Goal:** Let a phone use Vader-hosted ChatMPD without running local models on the phone or exposing llama.cpp/ComfyUI directly.

## Architecture

The phone is a thin PWA client. A small ChatMPD gateway owns the only LAN-facing listener and forwards authenticated commands to an injected ChatMPD command handler. llama.cpp and ComfyUI remain loopback-only.

The gateway uses Python standard-library HTTP components so the desktop build gains no web-framework dependency. Remote access is a later transport concern; the gateway itself must work over a trusted LAN and remain compatible with Tailscale/WireGuard.

## Security Model

- Pairing uses a short-lived one-time code generated on Vader.
- Successful pairing returns a high-entropy bearer token.
- Only a SHA-256 digest of each device token is stored locally.
- Device tokens are revocable and compared with constant-time equality.
- No cookie authentication and no wildcard CORS are used.
- Request bodies are size-bounded and JSON-only for API writes.
- API responses are `no-store` and include conservative browser security headers.
- The gateway never proxies raw llama.cpp or ComfyUI endpoints.
- Firewall, account, credential, and security-control changes remain outside gateway automation.

## Initial API

- `GET /` serves the mobile client.
- `GET /manifest.webmanifest` serves install metadata.
- `GET /api/health` returns minimal gateway status without private host details.
- `POST /api/pair` exchanges a valid one-time code for a device token.
- `POST /api/command` requires a bearer token and sends one plain-language request to ChatMPD.
- `GET /api/status` requires a bearer token and reports capability/runtime status supplied by ChatMPD.

## Lifecycle

The desktop application may start or stop the gateway. LAN binding is explicit and separate from internal loopback services. Stopping ChatMPD stops any gateway process it owns; a gateway must not silently alter Windows Firewall.

## Mobile UX

The page provides one command box, conversation/output area, connection state, and installable-PWA metadata. Pairing is entered once per device and the token is stored in browser local storage. The UI never asks the user to choose llama.cpp models, ComfyUI nodes, or specialist backends.

## Verification

Unit tests cover one-time pairing, expiration, hashed token persistence, revocation, authentication, body limits, headers, and command dispatch. A live smoke test must bind locally, pair a temporary client, execute a harmless command handler, and stop cleanly before desktop packaging is considered complete.
