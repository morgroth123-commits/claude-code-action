"""Authenticated private-network gateway and PWA shell for ChatMPD."""

from __future__ import annotations

import ipaddress
import json
import mimetypes
import sys
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from .conversation_library import ConversationLibrary
from .mobile_auth import DeviceCredentialStore


@dataclass(frozen=True)
class GatewayConfig:
    host: str = "0.0.0.0"
    port: int = 8765
    max_body_bytes: int = 65_536

    def __post_init__(self) -> None:
        if not 0 <= self.port <= 65_535:
            raise ValueError("port must be between 0 and 65535")
        if not 1 <= self.max_body_bytes <= 1_048_576:
            raise ValueError("max_body_bytes must be between 1 and 1048576")


def _asset_path(name: str) -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "assets" / name
    return Path(__file__).resolve().parents[1] / "assets" / name


def _private_client(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return bool(
        address.is_loopback
        or address.is_private
        or address.is_link_local
    )


class MobileGateway:
    """Serve ChatMPD to paired devices without exposing model backends."""

    def __init__(
        self,
        *,
        command_handler: Callable[..., Any],
        credential_store: DeviceCredentialStore | None = None,
        conversations: ConversationLibrary | None = None,
        assets_root: Path | None = None,
        status_handler: Callable[[], Any] | None = None,
        config: GatewayConfig | None = None,
    ) -> None:
        self.command_handler = command_handler
        self.credentials = credential_store or DeviceCredentialStore()
        self.conversations = conversations
        self.assets_root = None if assets_root is None else Path(assets_root)
        self.status_handler = status_handler or (lambda: {"mode": "ready"})
        self.config = config or GatewayConfig()
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            return self.config.port
        return int(self._server.server_address[1])

    def begin_pairing(self) -> str:
        return self.credentials.begin_pairing()

    def start(self) -> None:
        if self._server is not None:
            return
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ChatMPD"
            sys_version = ""

            def log_message(self, _format: str, *_args: object) -> None:
                return None

            def do_GET(self) -> None:  # noqa: N802
                owner._handle(self)

            def do_POST(self) -> None:  # noqa: N802
                owner._handle(self)

            def do_DELETE(self) -> None:  # noqa: N802
                owner._handle(self)

        self._server = ThreadingHTTPServer((self.config.host, self.config.port), Handler)
        self._thread = Thread(
            target=self._server.serve_forever,
            name="ChatMPD mobile gateway",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=3.0)

    def _handle(self, request: BaseHTTPRequestHandler) -> None:
        if not _private_client(request.client_address[0]):
            self._json(request, 403, {"error": "private network only"})
            return
        parsed = urlsplit(request.path)
        path = parsed.path
        if request.command == "GET" and path in {"/", "/index.html"}:
            if self.assets_root is not None:
                self._serve_web_asset(request, "index.html")
            else:
                self._bytes(request, 200, _INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if request.command == "GET" and path in {"/app.css", "/app.js", "/chatmpd-192.png", "/chatmpd-512.png"}:
            self._serve_web_asset(request, path.lstrip("/"))
            return
        if request.command == "GET" and path == "/manifest.webmanifest":
            self._json(request, 200, _MANIFEST)
            return
        if request.command == "GET" and path in {"/icon-192.png", "/icon-512.png"}:
            name = "chatmpd-192.png" if "192" in path else "chatmpd-512.png"
            self._serve_asset(request, name)
            return
        if request.command == "GET" and path == "/service-worker.js":
            self._bytes(request, 200, _SERVICE_WORKER.encode("utf-8"), "text/javascript; charset=utf-8")
            return
        if request.command == "GET" and path == "/api/client":
            self._json(request, 200, {"mode": "mobile"})
            return
        if request.command == "POST" and path == "/api/pair":
            self._pair(request)
            return
        if path.startswith("/api/") and not self._authorized(request):
            self._json(request, 401, {"error": "unauthorized"})
            return
        if request.command == "GET" and path == "/api/status":
            self._json(request, 200, self.status_handler())
            return
        if path == "/api/conversations" and self.conversations is not None:
            self._conversation_collection(request, parsed)
            return
        segments = [part for part in path.split("/") if part]
        if segments[:2] == ["api", "conversations"] and self.conversations is not None:
            self._conversation_item(request, segments[2:])
            return
        if request.command == "POST" and path == "/api/command":
            self._command(request)
            return
        self._json(request, 404, {"error": "not found"})

    def _conversation_collection(self, request: BaseHTTPRequestHandler, parsed: Any) -> None:
        assert self.conversations is not None
        if request.command == "GET":
            query = parse_qs(parsed.query).get("q", [""])[0]
            items = self.conversations.search(query) if query else self.conversations.list()
            self._json(request, 200, [asdict(item) for item in items])
            return
        if request.command == "POST":
            try:
                payload = self._read_json(request)
                document = self.conversations.create(payload.get("messages"))
            except (OSError, ValueError) as error:
                self._json(request, 400, {"error": str(error)[:300]})
                return
            self._json(request, 201, asdict(document))
            return
        self._json(request, 404, {"error": "not found"})

    def _conversation_item(self, request: BaseHTTPRequestHandler, segments: list[str]) -> None:
        assert self.conversations is not None
        if not segments:
            self._json(request, 404, {"error": "conversation id required"})
            return
        conversation_id = segments[0]
        try:
            if len(segments) == 1 and request.command == "GET":
                document = self.conversations.load(conversation_id)
                self._json(request, 200, asdict(document))
                return
            if len(segments) == 1 and request.command == "DELETE":
                deleted = self.conversations.delete(conversation_id)
                self._json(request, 200 if deleted else 404, {"deleted": deleted})
                return
            if len(segments) != 2 or request.command != "POST":
                self._json(request, 404, {"error": "not found"})
                return
            payload = self._read_json(request)
            action = segments[1]
            if action == "rename":
                document = self.conversations.rename(conversation_id, str(payload.get("title", "")))
            elif action == "pin":
                document = self.conversations.set_pinned(conversation_id, bool(payload.get("pinned")))
            elif action == "branch":
                count = payload.get("through_message_count")
                document = self.conversations.branch(conversation_id, None if count is None else int(count))
            else:
                self._json(request, 404, {"error": "not found"})
                return
            self._json(request, 200, asdict(document))
        except (OSError, ValueError, FileNotFoundError) as error:
            self._json(request, 400, {"error": str(error)[:300]})

    def _pair(self, request: BaseHTTPRequestHandler) -> None:
        try:
            payload = self._read_json(request)
            credential = self.credentials.pair(
                str(payload.get("code", "")),
                str(payload.get("device_name", "")),
            )
        except (ValueError, TypeError) as error:
            self._json(request, 400, {"error": str(error)})
            return
        self._json(
            request,
            200,
            {
                "device_id": credential.device_id,
                "device_name": credential.device_name,
                "token": credential.token,
            },
        )

    def _command(self, request: BaseHTTPRequestHandler) -> None:
        try:
            payload = self._read_json(request)
            text = str(payload.get("text", "")).strip()
            if not text:
                raise ValueError("Command text is required.")
            workspace = payload.get("workspace")
            conversation_id = str(payload.get("conversation_id") or "").strip()
            if conversation_id:
                result = self.command_handler(
                    text,
                    None if workspace is None else str(workspace),
                    conversation_id=conversation_id,
                )
            else:
                result = self.command_handler(
                    text,
                    None if workspace is None else str(workspace),
                )
        except (ValueError, TypeError) as error:
            self._json(request, 400, {"error": str(error)})
            return
        except Exception as error:
            self._json(request, 500, {"error": f"{type(error).__name__}: {error}"})
            return
        self._json(request, 200, result)

    def _authorized(self, request: BaseHTTPRequestHandler) -> bool:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return self.credentials.verify(header[7:].strip())

    def _read_json(self, request: BaseHTTPRequestHandler) -> dict[str, Any]:
        raw_length = request.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as error:
            raise ValueError("Invalid Content-Length.") from error
        if length < 0 or length > self.config.max_body_bytes:
            raise ValueError("Request body is too large.")
        raw = request.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return payload

    def _serve_web_asset(self, request: BaseHTTPRequestHandler, name: str) -> None:
        allowed = {"index.html", "app.css", "app.js", "chatmpd-192.png", "chatmpd-512.png"}
        if name not in allowed:
            self._json(request, 404, {"error": "asset unavailable"})
            return
        if self.assets_root is None:
            if name.startswith("chatmpd-"):
                self._serve_asset(request, name)
            else:
                self._json(request, 404, {"error": "asset unavailable"})
            return
        path = self.assets_root / name
        if not path.is_file():
            self._json(request, 404, {"error": "asset unavailable"})
            return
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._bytes(request, 200, path.read_bytes(), content_type)

    def _serve_asset(self, request: BaseHTTPRequestHandler, name: str) -> None:
        path = _asset_path(name)
        if not path.is_file():
            self._json(request, 404, {"error": "asset unavailable"})
            return
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._bytes(request, 200, path.read_bytes(), content_type)

    def _json(self, request: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._bytes(request, status, data, "application/json; charset=utf-8")

    @staticmethod
    def _bytes(
        request: BaseHTTPRequestHandler,
        status: int,
        data: bytes,
        content_type: str,
    ) -> None:
        request.send_response(status)
        request.send_header("Content-Type", content_type)
        request.send_header("Content-Length", str(len(data)))
        request.send_header("Cache-Control", "no-store")
        request.send_header("X-Content-Type-Options", "nosniff")
        request.send_header("Referrer-Policy", "no-referrer")
        request.send_header("X-Frame-Options", "DENY")
        request.end_headers()
        request.wfile.write(data)


_MANIFEST = {
    "name": "ChatMPD",
    "short_name": "ChatMPD",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#090909",
    "theme_color": "#101010",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ],
}

_SERVICE_WORKER = """
const CACHE='chatmpd-shell-v1';
const FILES=['/','/manifest.webmanifest','/icon-192.png','/icon-512.png'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(FILES))));
self.addEventListener('fetch',e=>{if(e.request.method==='GET')e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));});
""".strip()

_INDEX_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#101010">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/icon-192.png">
<title>ChatMPD</title>
<style>
:root{color-scheme:dark;font-family:Segoe UI,system-ui,sans-serif;background:#090909;color:#f4f4f4}
body{margin:0;min-height:100vh;background:radial-gradient(circle at top,#321208,#090909 42%)}
main{max-width:760px;margin:auto;padding:24px 16px 48px}
header{display:flex;align-items:center;gap:14px;margin-bottom:20px}
header img{width:58px;height:58px;border-radius:14px;object-fit:cover}
h1{font-size:1.7rem;margin:0}.muted{color:#aaa;font-size:.92rem}
.card{background:#151515;border:1px solid #303030;border-radius:18px;padding:16px;margin:12px 0}
textarea,input,button{box-sizing:border-box;width:100%;border-radius:12px;border:1px solid #444;background:#0e0e0e;color:#fff;padding:12px;font:inherit}
textarea{min-height:140px;resize:vertical}button{margin-top:10px;background:#c94617;border-color:#ed6f3b;font-weight:700}
button.secondary{background:#222;border-color:#444}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
pre{white-space:pre-wrap;word-break:break-word;background:#0b0b0b;padding:12px;border-radius:12px;min-height:70px}
@media(max-width:520px){.row{grid-template-columns:1fr}}
</style></head><body><main>
<header><img src="/icon-192.png" alt="ChatMPD"><div><h1>ChatMPD</h1><div class="muted">Local assistant</div></div></header>
<div class="card" id="pair"><strong>Pair this device</strong><p class="muted">Enter the one-time code shown by ChatMPD on your PC.</p>
<input id="code" inputmode="numeric" maxlength="8" placeholder="Pairing code"><input id="device" placeholder="Device name" value="My phone"><button onclick="pair()">Pair device</button></div>
<div class="card"><strong>Command</strong><textarea id="text" placeholder="Tell ChatMPD what you want done..."></textarea>
<input id="workspace" placeholder="Optional project folder on this PC"><button onclick="sendCommand()">Send to ChatMPD</button></div>
<div class="card"><div class="row"><button class="secondary" onclick="status()">Refresh status</button><button class="secondary" onclick="forget()">Forget this device</button></div><pre id="result">Ready.</pre></div>
<script>
const tokenKey='chatmpd-device-token';const result=document.getElementById('result');
function token(){return localStorage.getItem(tokenKey)||''}
function show(v){result.textContent=typeof v==='string'?v:JSON.stringify(v,null,2)}
async function api(path,options={}){const headers={'Content-Type':'application/json',...(options.headers||{})};if(token())headers.Authorization='Bearer '+token();const r=await fetch(path,{...options,headers});const data=await r.json();if(!r.ok)throw new Error(data.error||('HTTP '+r.status));return data}
async function pair(){try{const data=await api('/api/pair',{method:'POST',body:JSON.stringify({code:document.getElementById('code').value,device_name:document.getElementById('device').value})});localStorage.setItem(tokenKey,data.token);show('Paired as '+data.device_name);document.getElementById('pair').hidden=true}catch(e){show(e.message)}}
async function sendCommand(){try{show('Working locally...');const body={text:document.getElementById('text').value};const w=document.getElementById('workspace').value.trim();if(w)body.workspace=w;show(await api('/api/command',{method:'POST',body:JSON.stringify(body)}))}catch(e){show(e.message)}}
async function status(){try{show(await api('/api/status'))}catch(e){show(e.message)}}
function forget(){localStorage.removeItem(tokenKey);document.getElementById('pair').hidden=false;show('Device credential removed from this phone. Revoke it in ChatMPD to invalidate it server-side.')}
if(token())document.getElementById('pair').hidden=true;
if('serviceWorker' in navigator)navigator.serviceWorker.register('/service-worker.js').catch(()=>{});
</script></main></body></html>"""
