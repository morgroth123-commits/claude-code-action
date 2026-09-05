"""Native Windows WebView2 host for the modern ChatMPD conversation UI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from .conversation_library import ConversationLibrary
from .orchestrator import ChatMPDOrchestrator
from .web_service import WebAppService


def web_assets_root() -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "chatmpd" / "web"
    return Path(__file__).resolve().parent / "web"


def _default_service(orchestrator: ChatMPDOrchestrator) -> WebAppService:
    store = getattr(orchestrator.assistant, "_store", None)
    root = getattr(store, "root", None)
    return WebAppService(
        orchestrator,
        ConversationLibrary(root),
        assets_root=web_assets_root(),
    )


ServiceFactory = Callable[[ChatMPDOrchestrator], Any]

def launch_webview(
    orchestrator: ChatMPDOrchestrator,
    *,
    webview_module: Any | None = None,
    service_factory: ServiceFactory | None = None,
) -> None:
    service = (service_factory or _default_service)(orchestrator)
    try:
        if webview_module is None:
            try:
                import webview as webview_module
            except ImportError as error:
                raise RuntimeError(
                    "The ChatMPD desktop UI requires pywebview/WebView2. "
                    "Run the ChatMPD installer again or use the local browser UI."
                ) from error
        service.start()
        webview_module.create_window(
            "ChatMPD",
            service.url,
            width=1180,
            height=720,
            min_size=(720, 520),
            maximized=True,
            background_color="#212121",
        )
        webview_module.start(gui="edgechromium", debug=False)
    finally:
        service.stop()
        orchestrator.close()
