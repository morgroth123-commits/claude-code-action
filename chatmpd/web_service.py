"""Loopback-only web application service for the modern ChatMPD desktop UI."""

from __future__ import annotations

import base64
import io
import ipaddress
import json
import mimetypes
import socket
import subprocess
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock, Thread
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from .conversation_library import ConversationLibrary
from .mobile_gateway import GatewayConfig, MobileGateway
from .orchestrator import ChatMPDOrchestrator, CommandResult


_STATUS_LABELS = {
    "queued": "Understanding request",
    "running": "Working locally",
    "cancelling": "Stopping safely",
    "cancelled": "Stopped",
    "completed": "Finishing up",
    "failed": "Needs attention",
    "needs_context": "Checking project",
}

_UPLOAD_MAX_BYTES = 16 * 1024 * 1024


@dataclass
class _Job:
    job_id: str
    text: str
    workspace: str | None
    conversation_id: str
    status: str = "queued"
    cancel_requested: bool = False
    result: dict[str, Any] | None = None
    error: str | None = None
    status_label: str = "Understanding request"
    attachment_ids: tuple[str, ...] = ()



class WebAppService:
    """Serve a local UI and serialize work through one ChatMPD orchestrator."""

    def __init__(
        self,
        orchestrator: ChatMPDOrchestrator,
        conversations: ConversationLibrary,
        *,
        assets_root: Path,
        max_body_bytes: int = 131_072,
        platform_services: Any | None = None,
        folder_picker: Callable[[], str | None] | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.conversations = conversations
        self.assets_root = Path(assets_root)
        self.max_body_bytes = int(max_body_bytes)
        self.platform_services = platform_services or getattr(orchestrator, "platform_services", None)
        self._folder_picker = folder_picker or self._native_folder_picker
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None
        self._worker: Thread | None = None
        self._lock = RLock()
        self._jobs: dict[str, _Job] = {}
        self._active_job_id: str | None = None
        self._mobile: MobileGateway | None = None
        self._mobile_session: dict[str, Any] | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            return 0
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

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

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = Thread(
            target=self._server.serve_forever,
            name="ChatMPD desktop web service",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_mobile_gateway()
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=3.0)

    def _handle(self, request: BaseHTTPRequestHandler) -> None:
        if not self._is_loopback(request.client_address[0]):
            self._json(request, 403, {"error": "loopback clients only"})
            return
        parsed = urlsplit(request.path)
        path = parsed.path
        segments = [part for part in path.split("/") if part]

        if request.command == "GET" and path in {"/", "/index.html"}:
            self._serve_asset(request, "index.html")
            return
        if request.command == "GET" and path in {"/app.css", "/app.js", "/chatmpd-192.png", "/chatmpd-512.png"}:
            self._serve_asset(request, path.lstrip("/"))
            return
        if request.command == "GET" and path == "/api/client":
            self._json(request, 200, {"mode": "desktop"})
            return
        if request.command == "POST" and path == "/api/system/select-folder":
            try:
                selected = self._folder_picker()
                self._json(request, 200, {"path": str(selected or "")})
            except Exception as error:
                self._json(request, 400, {"error": f"Folder picker failed: {type(error).__name__}"})
            return
        if path == "/api/mobile/start" and request.command == "POST":
            self._start_mobile_gateway(request)
            return
        if path == "/api/mobile/status" and request.command == "GET":
            self._json(request, 200, self._mobile_status())
            return
        if path == "/api/mobile/stop" and request.command == "POST":
            self._stop_mobile_gateway()
            self._json(request, 200, {"active": False})
            return
        if segments[:2] == ["api", "platform"]:
            self._platform_route(request, segments[2:], parsed)
            return
        if path == "/api/conversations" and request.command == "GET":
            query = parse_qs(parsed.query).get("q", [""])[0]
            items = self.conversations.search(query) if query else self.conversations.list()
            self._json(request, 200, [asdict(item) for item in items])
            return
        if path == "/api/conversations" and request.command == "POST":
            payload = self._read_json(request)
            document = self.conversations.create(payload.get("messages"))
            self._json(request, 201, asdict(document))
            return
        if segments[:1] == ["api"] and len(segments) >= 2:
            if segments[1] == "conversations":
                self._conversation_route(request, segments[2:])
                return
            if segments[1] == "jobs":
                self._job_route(request, segments[2:])
                return
        self._json(request, 404, {"error": "not found"})

    def _platform_route(self, request: BaseHTTPRequestHandler, segments: list[str], parsed: Any) -> None:
        services = self.platform_services
        if services is None:
            self._json(request, 404, {"error": "platform services are unavailable"})
            return
        section = segments[0] if segments else "summary"
        try:
            if section == "summary" and request.command == "GET":
                self._json(request, 200, services.summary())
                return
            if section == "performance":
                if request.command == "GET":
                    history = services.performance.history(limit=20)
                    self._json(request, 200, {
                        "status": services.performance.status(),
                        "history": [asdict(item) for item in history],
                        "latest": None if not history else asdict(history[0]),
                    })
                    return
                if request.command == "POST" and len(segments) == 2 and segments[1] == "analyze":
                    self._json(request, 200, asdict(services.performance.analyze()))
                    return
                if request.command == "POST" and len(segments) == 2 and segments[1] == "optimize":
                    payload = self._read_json(request)
                    result = services.performance.optimize_current(
                        confirmed=bool(payload.get("confirmed", False))
                    )
                    self._json(request, 200, asdict(result))
                    return
                if request.command == "POST" and len(segments) == 2 and segments[1] == "apply":
                    payload = self._read_json(request)
                    result = services.performance.apply(str(payload.get("mode", "")), confirmed=bool(payload.get("confirmed", False)))
                    self._json(request, 200, asdict(result))
                    return
                if request.command == "POST" and len(segments) == 2 and segments[1] == "restore":
                    payload = self._read_json(request)
                    self._json(request, 200, asdict(services.performance.restore(confirmed=bool(payload.get("confirmed", False)))))
                    return
                if request.command == "POST" and len(segments) == 2 and segments[1] == "adaptive":
                    payload = self._read_json(request)
                    result = services.performance.set_adaptive(
                        bool(payload.get("enabled", False)),
                        base_mode=str(payload.get("base_mode") or "balanced"),
                        start_thread=bool(payload.get("start_thread", True)),
                    )
                    self._json(request, 200, result)
                    return
            if section == "memory":
                if request.command == "GET":
                    self._json(request, 200, [asdict(item) for item in services.memory.list()])
                    return
                if request.command == "POST" and len(segments) == 1:
                    payload = self._read_json(request)
                    item = services.memory.add(
                        str(payload.get("content", "")),
                        kind=str(payload.get("kind") or "fact"),
                        source=str(payload.get("source") or "control-center"),
                        pinned=bool(payload.get("pinned", False)),
                    )
                    self._json(request, 201, asdict(item))
                    return
                if request.command == "DELETE" and len(segments) == 2:
                    deleted = services.memory.delete(segments[1])
                    self._json(request, 200 if deleted else 404, {"deleted": deleted})
                    return
            if section == "knowledge":
                if request.command == "GET":
                    self._json(request, 200, [asdict(item) for item in services.knowledge.list()])
                    return
                if request.command == "POST":
                    payload = self._read_json(request)
                    item = services.knowledge.ingest(Path(str(payload.get("path", ""))))
                    self._json(request, 201, asdict(item))
                    return
            if section == "capabilities" and request.command == "GET":
                self._json(request, 200, [asdict(item) for item in services.capabilities.list()])
                return
            if section == "models" and request.command == "GET":
                items = []
                for model in services.models.registry.models:
                    items.append({
                        "name": model.name, "path": str(model.path), "family": model.family,
                        "roles": [role.value for role in model.roles],
                        "parameter_billions": model.parameter_billions,
                    })
                self._json(request, 200, {"models": items, "benchmarks": [asdict(item) for item in services.models.benchmarks.list()]})
                return
            if section == "workflows":
                if request.command == "GET":
                    self._json(request, 200, [asdict(item) for item in services.workflows.list()])
                    return
                if request.command == "POST" and len(segments) == 1:
                    payload = self._read_json(request)
                    item = services.workflows.save(
                        str(payload.get("name", "")), str(payload.get("command", "")),
                        workspace=payload.get("workspace"),
                    )
                    self._json(request, 201, asdict(item))
                    return
                if request.command == "POST" and len(segments) == 3 and segments[2] == "run":
                    item = services.workflows.get(segments[1])
                    result = self.orchestrator.command(item.command, workspace=item.workspace)
                    self._json(request, 200, result.as_dict())
                    return
            if section == "automations":
                if request.command == "GET":
                    self._json(request, 200, [asdict(item) for item in services.automations.list()])
                    return
                if request.command == "POST" and len(segments) == 1:
                    payload = self._read_json(request)
                    item = services.automations.create(
                        str(payload.get("name", "")), str(payload.get("command", "")),
                        interval_seconds=int(payload.get("interval_seconds", 3600)),
                        condition_contains=payload.get("condition_contains"),
                    )
                    self._json(request, 201, asdict(item))
                    return
                if request.command == "DELETE" and len(segments) == 2:
                    deleted = services.automations.delete(segments[1])
                    self._json(request, 200 if deleted else 404, {"deleted": deleted})
                    return
                if request.command == "POST" and len(segments) == 3 and segments[2] == "enabled":
                    payload = self._read_json(request)
                    item = services.automations.set_enabled(segments[1], bool(payload.get("enabled")))
                    self._json(request, 200, asdict(item))
                    return
            if section == "activity" and request.command == "GET":
                self._json(request, 200, [asdict(item) for item in services.activity.list()])
                return
            if section == "recovery":
                if request.command == "GET":
                    self._json(request, 200, [asdict(item) for item in services.recovery.list()])
                    return
                if request.command == "POST" and len(segments) == 3 and segments[2] == "rollback":
                    payload = self._read_json(request)
                    if not bool(payload.get("confirmed")):
                        raise PermissionError("Rollback requires explicit confirmation.")
                    restored = services.recovery.rollback(segments[1])
                    self._json(request, 200, {"restored": [str(item) for item in restored]})
                    return
            if section == "prompts":
                if request.command == "GET":
                    self._json(request, 200, {"templates": services.prompts.templates()})
                    return
                if request.command == "POST":
                    payload = self._read_json(request)
                    result = services.prompts.optimize(
                        str(payload.get("goal", "")), context=str(payload.get("context", "")),
                        constraints=payload.get("constraints") or (), desired_result=str(payload.get("desired_result", "")),
                        verification=str(payload.get("verification", "")),
                    )
                    self._json(request, 200, {"prompt": result})
                    return
            if section == "packs":
                if request.command == "GET":
                    self._json(request, 200, [asdict(item) for item in services.packs.list()])
                    return
                if request.command == "POST" and len(segments) == 3:
                    if segments[2] == "install":
                        self._json(request, 200, asdict(services.packs.install(segments[1])))
                        return
                    if segments[2] == "uninstall":
                        self._json(request, 200, {"uninstalled": services.packs.uninstall(segments[1])})
                        return
            if section == "extensions":
                if request.command == "GET":
                    self._json(request, 200, [asdict(item) for item in services.extensions.discover()])
                    return
                if request.command == "POST" and len(segments) == 2 and segments[1] == "skill":
                    payload = self._read_json(request)
                    folder = services.wizard.create_skill(
                        str(payload.get("name", "")),
                        capability_id=str(payload.get("capability_id", "")),
                        description=str(payload.get("description", "")),
                        content_categories=payload.get("content_categories") or (),
                    )
                    self._json(request, 201, {"path": str(folder)})
                    return
            if section == "doctor":
                if request.command == "GET":
                    report = services.doctor.run()
                    self._json(request, 200, {"ready": report.ready, "checks": [asdict(item) for item in report.checks]})
                    return
                if request.command == "POST" and len(segments) == 2 and segments[1] == "repair":
                    self._json(request, 200, {"actions": list(services.doctor.repair())})
                    return
            if section == "lmstudio" and request.command == "GET":
                self._json(request, 200, services.summary()["lm_studio"])
                return
            if section == "bionic":
                if request.command == "GET":
                    self._json(request, 200, services.bionic.status())
                    return
                if request.command == "POST" and len(segments) == 2 and segments[1] == "open":
                    services.bionic.open()
                    self._json(request, 200, {"opened": True})
                    return
            if section == "civitai":
                if request.command == "GET":
                    self._json(request, 200, services.civitai.status())
                    return
                if request.command == "POST" and len(segments) == 2 and segments[1] == "tools":
                    self._json(request, 200, {"tools": list(services.civitai.list_tools())})
                    return
                if request.command == "POST" and len(segments) == 2 and segments[1] == "call":
                    payload = self._read_json(request)
                    result = services.civitai.call(
                        str(payload.get("tool_name", "")),
                        dict(payload.get("arguments") or {}),
                        confirmed=bool(payload.get("confirmed", False)),
                    )
                    self._json(request, 200, result)
                    return
            if section == "mod-sources" and request.command == "GET":
                self._json(request, 200, {
                    "esoui": services.esoui.policy(),
                    "nexus": {"site": services.nexus.site_root, "api": services.nexus.api_root,
                              "api_key_configured": "nexus-api-key" in services.secrets.names()},
                })
                return
            if section == "voice" and request.command == "GET":
                self._json(request, 200, {"tts": "ready", "transcription": services.voice.transcription_health()})
                return
            if section == "vision" and request.command == "GET":
                self._json(request, 200, services.vision.health())
                return
            if section == "secrets":
                if request.command == "GET":
                    self._json(request, 200, {"names": list(services.secrets.names())})
                    return
                if request.command == "POST" and len(segments) == 2:
                    payload = self._read_json(request)
                    if not bool(payload.get("confirmed")):
                        raise PermissionError("Saving credentials requires explicit confirmation.")
                    services.secrets.set(segments[1], str(payload.get("value", "")))
                    self._json(request, 200, {"saved": segments[1]})
                    return
            if section == "export" and request.command == "POST":
                payload = self._read_json(request)
                include = [Path(str(item)) for item in payload.get("include_paths") or ()]
                destination = Path(str(payload.get("destination") or (services.paths.exports / "ChatMPD.chatmpdpack")))
                result = services.exporter.create_pack(
                    destination,
                    include_paths=include,
                    metadata={"edition": "generic", "unlimited_local_use": True},
                )
                self._json(request, 201, {"path": str(result)})
                return
            self._json(request, 404, {"error": "platform route not found"})
        except PermissionError as error:
            self._json(request, 403, {"error": str(error)[:500]})
        except (OSError, ValueError, KeyError, FileNotFoundError, RuntimeError, TypeError) as error:
            self._json(request, 400, {"error": f"{type(error).__name__}: {error}"[:500]})

    def _conversation_route(
        self, request: BaseHTTPRequestHandler, segments: list[str]
    ) -> None:
        if not segments:
            self._json(request, 404, {"error": "conversation id required"})
            return
        conversation_id = segments[0]
        try:
            if len(segments) == 1 and request.command == "GET":
                self._json(request, 200, asdict(self.conversations.load(conversation_id)))
                return
            if len(segments) == 1 and request.command == "DELETE":
                deleted = self.conversations.delete(conversation_id)
                self._json(request, 200 if deleted else 404, {"deleted": deleted})
                return
            if len(segments) >= 2 and segments[1] == "attachments":
                self._attachment_route(request, conversation_id, segments[2:])
                return
            if len(segments) != 2 or request.command != "POST":
                self._json(request, 404, {"error": "not found"})
                return
            action = segments[1]
            payload = self._read_json(request)
            if action == "rename":
                document = self.conversations.rename(conversation_id, str(payload.get("title", "")))
            elif action == "pin":
                document = self.conversations.set_pinned(conversation_id, bool(payload.get("pinned")))
            elif action == "branch":
                count = payload.get("through_message_count")
                document = self.conversations.branch(conversation_id, None if count is None else int(count))
            elif action == "workspace":
                document = self.conversations.set_workspace(
                    conversation_id, payload.get("workspace")
                )
            else:
                self._json(request, 404, {"error": "not found"})
                return
            self._json(request, 200, asdict(document))
        except (OSError, ValueError, FileNotFoundError, KeyError) as error:
            self._json(request, 400, {"error": self._user_error(error)})


    def _attachment_route(
        self,
        request: BaseHTTPRequestHandler,
        conversation_id: str,
        segments: list[str],
    ) -> None:
        store = self._attachment_store()
        if store is None:
            self._json(request, 404, {"error": "Attachments are unavailable right now."})
            return
        self.conversations.load(conversation_id)
        if not segments and request.command == "GET":
            items = []
            for record in store.list(conversation_id):
                items.append({
                    "attachment_id": record.attachment_id,
                    "original_name": record.original_name,
                    "content_type": record.content_type,
                    "size_bytes": record.size_bytes,
                    "created_at": record.created_at,
                })
            self._json(request, 200, items)
            return
        if not segments and request.command == "POST":
            payload = self._read_json(request, max_bytes=int(_UPLOAD_MAX_BYTES * 1.4) + 4096)
            name = str(payload.get("filename") or payload.get("original_name") or "attachment").strip()
            content_type = str(payload.get("content_type") or "application/octet-stream")
            encoded = str(payload.get("data") or payload.get("content_base64") or "")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except Exception as error:
                raise ValueError("Attachment data must be valid base64.") from error
            if len(raw) > _UPLOAD_MAX_BYTES:
                raise ValueError("That file is too large to attach here (16 MB limit).")
            record = store.import_bytes(
                raw,
                original_name=name,
                conversation_id=conversation_id,
                content_type=content_type,
            )
            self._json(request, 201, {
                "attachment_id": record.attachment_id,
                "original_name": record.original_name,
                "content_type": record.content_type,
                "size_bytes": record.size_bytes,
                "created_at": record.created_at,
            })
            return
        if len(segments) == 1 and request.command == "DELETE":
            attachment_id = segments[0]
            try:
                record = store.get(attachment_id)
            except KeyError:
                self._json(request, 404, {"error": "Attachment not found."})
                return
            if record.conversation_id != conversation_id:
                self._json(request, 403, {"error": "That attachment belongs to another chat."})
                return
            deleted = store.delete(attachment_id)
            self._json(request, 200 if deleted else 404, {"deleted": deleted})
            return
        self._json(request, 404, {"error": "not found"})

    def _attachment_store(self) -> Any | None:
        services = self.platform_services
        if services is None:
            return None
        return getattr(services, "attachments", None)

    def _job_route(self, request: BaseHTTPRequestHandler, segments: list[str]) -> None:
        if not segments and request.command == "POST":
            try:
                payload = self._read_json(request)
                text = str(payload.get("text", "")).strip()
                if not text:
                    raise ValueError("Command text is required.")
                conversation_id = str(payload.get("conversation_id") or "").strip()
                if conversation_id:
                    self.conversations.load(conversation_id)
                else:
                    conversation_id = self.conversations.create().conversation_id
                raw_workspace = payload.get("workspace")
                workspace = None if raw_workspace is None else str(raw_workspace).strip() or None
                attachment_ids = self._validated_attachment_ids(
                    conversation_id, payload.get("attachment_ids") or ()
                )
            except (OSError, ValueError, FileNotFoundError, KeyError) as error:
                self._json(request, 400, {"error": self._user_error(error)})
                return
            self._create_job(
                request, text, workspace, conversation_id, attachment_ids=attachment_ids
            )
            return
        if len(segments) == 1 and request.command == "GET":
            job = self._jobs.get(segments[0])
            if job is None:
                self._json(request, 404, {"error": "job not found"})
            else:
                self._json(request, 200, self._public_job(job))
            return
        if len(segments) == 2 and segments[1] == "cancel" and request.command == "POST":
            self._cancel_job(request, segments[0])
            return
        self._json(request, 404, {"error": "not found"})

    def _validated_attachment_ids(
        self, conversation_id: str, raw_ids: Any
    ) -> tuple[str, ...]:
        if raw_ids in (None, "", []):
            return ()
        if not isinstance(raw_ids, (list, tuple)):
            raise ValueError("attachment_ids must be a list.")
        store = self._attachment_store()
        cleaned: list[str] = []
        for item in raw_ids:
            attachment_id = str(item).strip()
            if not attachment_id:
                continue
            if store is None:
                raise ValueError("Attachments are unavailable right now.")
            record = store.get(attachment_id)
            if record.conversation_id != conversation_id:
                raise ValueError("One or more attachments do not belong to this chat.")
            cleaned.append(attachment_id)
        return tuple(cleaned)

    def _create_job(
        self, request: BaseHTTPRequestHandler, text: str,
        workspace: str | None, conversation_id: str,
        *, attachment_ids: tuple[str, ...] = (),
    ) -> None:
        with self._lock:
            active = self._jobs.get(self._active_job_id or "")
            if active is not None and active.status in {"queued", "running", "cancelling"}:
                self._json(request, 409, {"error": "ChatMPD is busy with another job."})
                return
            job = _Job(
                uuid4().hex,
                text,
                workspace,
                conversation_id,
                status_label=_STATUS_LABELS["queued"],
                attachment_ids=attachment_ids,
            )
            self._jobs[job.job_id] = job
            self._active_job_id = job.job_id
            self._worker = Thread(target=self._run_job, args=(job.job_id,), name="ChatMPD web job", daemon=True)
            self._worker.start()
        self._json(request, 202, self._public_job(job))

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.cancel_requested:
                job.status = "cancelled"
                job.status_label = _STATUS_LABELS["cancelled"]
                self._active_job_id = None
                return
            job.status = "running"
            job.status_label = _STATUS_LABELS["running"]
        try:
            loader = getattr(self.orchestrator.assistant, "load_conversation", None)
            if callable(loader):
                loader(job.conversation_id)
            command_text = self._command_text_with_attachments(job)
            result = self.orchestrator.command(command_text, workspace=job.workspace)
            with self._lock:
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.status_label = _STATUS_LABELS["cancelled"]
                    return
            self._persist_result(job, result)
            with self._lock:
                job.result = result.as_dict()
                details = result.details if isinstance(result.details, dict) else {}
                if str(details.get("status") or "") == "needs_context":
                    job.status = "needs_context"
                    job.status_label = str(
                        details.get("status_label") or _STATUS_LABELS["needs_context"]
                    )
                else:
                    job.status = "completed"
                    job.status_label = str(
                        details.get("status_label") or _STATUS_LABELS["completed"]
                    )
        except Exception as error:
            with self._lock:
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.status_label = _STATUS_LABELS["cancelled"]
                else:
                    job.status = "failed"
                    job.status_label = _STATUS_LABELS["failed"]
                    job.error = self._user_error(error)
        finally:
            with self._lock:
                if self._active_job_id == job_id:
                    self._active_job_id = None

    def _command_text_with_attachments(self, job: _Job) -> str:
        if not job.attachment_ids:
            return job.text
        store = self._attachment_store()
        if store is None:
            return job.text
        notes: list[str] = []
        for attachment_id in job.attachment_ids:
            try:
                record = store.get(attachment_id)
            except KeyError:
                continue
            if record.conversation_id != job.conversation_id:
                continue
            snippet = ""
            if record.content_type.startswith("text/") or record.original_name.lower().endswith(
                (".txt", ".md", ".py", ".json", ".csv", ".log")
            ):
                try:
                    raw = record.path.read_bytes()[:8_000]
                    snippet = raw.decode("utf-8", errors="replace").strip()
                except OSError:
                    snippet = ""
            if snippet:
                notes.append(
                    f"[Attachment {record.original_name}]\n{snippet[:4000]}"
                )
            else:
                notes.append(
                    f"[Attachment {record.original_name} ({record.content_type}, {record.size_bytes} bytes)]"
                )
        if not notes:
            return job.text
        return job.text + "\n\n" + "\n\n".join(notes)


    def _persist_result(self, job: _Job, result: CommandResult) -> None:
        document = self.conversations.load(job.conversation_id)
        messages = list(document.messages)
        pair = [
            {"role": "user", "content": job.text},
            {"role": "assistant", "content": result.message},
        ]
        if len(messages) < 2 or messages[-2:] != pair:
            messages.extend(pair)
            self.conversations.save_messages(job.conversation_id, messages)

    def _cancel_job(self, request: BaseHTTPRequestHandler, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                self._json(request, 404, {"error": "job not found"})
                return
            if job.status in {"completed", "failed", "cancelled", "needs_context"}:
                self._json(request, 200, self._public_job(job))
                return
            job.cancel_requested = True
            job.status = "cancelled" if job.status == "queued" else "cancelling"
            job.status_label = _STATUS_LABELS.get(job.status, "Stopping safely")
        try:
            decision = self.orchestrator.router.classify(job.text)
            if getattr(decision, "capability", "") == "chat":
                release = getattr(self.orchestrator.assistant, "release_runtime", None)
                if callable(release):
                    release()
        except Exception:
            pass
        self._json(request, 202, self._public_job(job))

    def _mobile_command(
        self, text: str, workspace: str | None = None, *, conversation_id: str | None = None
    ) -> dict[str, Any]:
        target = str(conversation_id or "").strip()
        if target:
            self.conversations.load(target)
            loader = getattr(self.orchestrator.assistant, "load_conversation", None)
            if callable(loader):
                loader(target)
        result = self.orchestrator.command(text, workspace=workspace)
        if target:
            document = self.conversations.load(target)
            pair = [
                {"role": "user", "content": text},
                {"role": "assistant", "content": result.message},
            ]
            messages = list(document.messages)
            if len(messages) < 2 or messages[-2:] != pair:
                messages.extend(pair)
                self.conversations.save_messages(target, messages)
        return result.as_dict()

    def _start_mobile_gateway(self, request: BaseHTTPRequestHandler) -> None:
        if self._mobile is None:
            gateway = MobileGateway(
                command_handler=self._mobile_command,
                conversations=self.conversations,
                assets_root=self.assets_root,
                status_handler=lambda: {"mode": "ready"},
                config=GatewayConfig(host="0.0.0.0", port=0),
            )
            gateway.start()
            self._mobile = gateway
        code = self._mobile.begin_pairing()
        address = self._lan_mobile_address(self._mobile.port)
        setup_url = f"{address}?pair={code}"
        self._mobile_session = {
            "active": True,
            "address": address,
            "pairing_code": code,
            "setup_url": setup_url,
            "qr_url": self._qr_data_url(setup_url),
        }
        self._json(request, 200, self._mobile_session)

    def _mobile_status(self) -> dict[str, Any]:
        if self._mobile is None or self._mobile_session is None:
            return {"active": False}
        return dict(self._mobile_session)

    def _stop_mobile_gateway(self) -> None:
        gateway = self._mobile
        self._mobile = None
        self._mobile_session = None
        if gateway is not None:
            gateway.stop()

    @staticmethod
    def _lan_mobile_address(port: int) -> str:
        candidates: list[str] = []
        try:
            for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
                address = str(item[4][0])
                parsed = ipaddress.ip_address(address)
                if parsed.is_private and not parsed.is_loopback:
                    candidates.append(address)
        except (OSError, ValueError, IndexError, TypeError):
            pass
        host = candidates[0] if candidates else "127.0.0.1"
        return f"http://{host}:{int(port)}/"

    @staticmethod
    def _qr_data_url(value: str) -> str:
        try:
            import qrcode
            import qrcode.image.svg
            image = qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage)
            stream = io.BytesIO()
            image.save(stream)
            encoded = base64.b64encode(stream.getvalue()).decode("ascii")
            return f"data:image/svg+xml;base64,{encoded}"
        except Exception:
            return ""

    @staticmethod
    def _native_folder_picker() -> str | None:
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog=New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dialog.Description='Choose a ChatMPD project folder'; "
            "$dialog.ShowNewFolderButton=$false; "
            "if($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK){"
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
            "Write-Output $dialog.SelectedPath}"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
            capture_output=True, text=True, timeout=300, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            raise RuntimeError("Native folder picker failed.")
        value = completed.stdout.strip()
        return value or None

    @staticmethod
    def _public_job(job: _Job) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": job.job_id,
            "status": job.status,
            "status_label": job.status_label or _STATUS_LABELS.get(job.status, "Working locally"),
            "conversation_id": job.conversation_id,
        }
        if job.result is not None and job.status in {"completed", "needs_context"}:
            payload["result"] = job.result
        if job.error and job.status == "failed":
            payload["error"] = job.error
        return payload

    @staticmethod
    def _user_error(error: BaseException) -> str:
        message = " ".join(str(error).split()).strip()
        if not message:
            message = "Something went wrong while ChatMPD was working."
        # Strip exception class prefixes from default formatting.
        if ": " in message and message.split(": ", 1)[0].endswith("Error"):
            message = message.split(": ", 1)[1]
        return message[:400]

    @staticmethod
    def _is_loopback(host: str) -> bool:
        try:
            return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
        except ValueError:
            return False

    def _read_json(
        self, request: BaseHTTPRequestHandler, *, max_bytes: int | None = None
    ) -> dict[str, Any]:
        try:
            length = int(request.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid Content-Length.") from error
        limit = self.max_body_bytes if max_bytes is None else int(max_bytes)
        if length < 0 or length > limit:
            raise ValueError("Request body is too large.")
        raw = request.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object.")
        return payload

    def _serve_asset(self, request: BaseHTTPRequestHandler, name: str) -> None:
        if name not in {"index.html", "app.css", "app.js", "chatmpd-192.png", "chatmpd-512.png"}:
            self._json(request, 404, {"error": "asset not found"})
            return
        path = self.assets_root / name
        if not path.is_file():
            self._json(request, 404, {"error": "asset not found"})
            return
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._bytes(request, 200, path.read_bytes(), content_type)

    def _json(self, request: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
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
