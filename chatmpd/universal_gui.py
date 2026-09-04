"""Universal desktop and mobile front door for ChatMPD."""

from __future__ import annotations

import ipaddress
import json
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable

from .mobile_gateway import GatewayConfig, MobileGateway
from .orchestrator import ChatMPDOrchestrator, CommandResult


@dataclass(frozen=True)
class UniversalSnapshot:
    busy: bool
    status: str
    capability: str = "ready"
    message: str = ""
    details: dict[str, Any] | None = None


class UniversalController:
    """Execute routed ChatMPD requests without blocking Tk."""

    def __init__(self, *, command_handler: Callable[..., CommandResult], schedule: Callable, publish: Callable) -> None:
        self._command_handler = command_handler
        self._schedule = schedule
        self._publish = publish
        self._lock = Lock()
        self._busy = False

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def start(self, text: str, workspace: str = "") -> bool:
        prompt = str(text).strip()
        if not prompt:
            self._publish(UniversalSnapshot(False, "Describe what you want ChatMPD to do."))
            return False
        with self._lock:
            if self._busy:
                self._publish(UniversalSnapshot(True, "ChatMPD is already working locally."))
                return False
            self._busy = True
        self._publish(UniversalSnapshot(True, "Working locally...", "routing"))
        selected = str(workspace).strip() or None
        Thread(
            target=self._run,
            args=(prompt, selected),
            name="ChatMPD universal command",
            daemon=False,
        ).start()
        return True

    def _run(self, prompt: str, workspace: str | None) -> None:
        try:
            result = self._command_handler(prompt, workspace=workspace)
            snapshot = UniversalSnapshot(
                False, "Ready.", result.capability, result.message, dict(result.details)
            )
        except Exception as error:
            detail = " ".join(str(error).split())[:500] or type(error).__name__
            snapshot = UniversalSnapshot(False, f"Needs attention: {detail}", "error", detail, {})
        self._schedule(lambda snapshot=snapshot: self._finish(snapshot))

    def _finish(self, snapshot: UniversalSnapshot) -> None:
        with self._lock:
            self._busy = False
        self._publish(snapshot)


def asset_path(name: str) -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "assets" / name
    return Path(__file__).resolve().parents[1] / "assets" / name


def _default_resolver(hostname: str) -> list[tuple[Any, ...]]:
    return socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_STREAM)


def local_mobile_url(
    port: int,
    *,
    hostname: str | None = None,
    resolver: Callable[[str], list[tuple[Any, ...]]] = _default_resolver,
) -> str:
    host = hostname or socket.gethostname()
    candidates: list[str] = []
    try:
        for item in resolver(host):
            address = str(item[4][0])
            parsed = ipaddress.ip_address(address)
            if parsed.version == 4 and parsed.is_private and not parsed.is_loopback:
                candidates.append(address)
    except (OSError, ValueError, IndexError, TypeError):
        candidates = []
    address = candidates[0] if candidates else "127.0.0.1"
    return f"http://{address}:{int(port)}/"


@dataclass
class MobileSession:
    gateway: MobileGateway
    url: str
    pairing_code: str


def start_mobile_session(orchestrator: ChatMPDOrchestrator) -> MobileSession:
    gateway = MobileGateway(
        command_handler=lambda text, workspace=None: orchestrator.command(
            text, workspace=workspace
        ).as_dict(),
        status_handler=lambda: {
            "mode": "ready",
            "conversation_id": orchestrator.assistant.conversation_id,
        },
        config=GatewayConfig(host="0.0.0.0", port=8765),
    )
    gateway.start()
    code = gateway.begin_pairing()
    return MobileSession(gateway, local_mobile_url(gateway.port), code)


class UniversalWindow:
    """Single-composer native Windows UI for the full ChatMPD orchestrator."""

    def __init__(self, root: Any, orchestrator: ChatMPDOrchestrator) -> None:
        import tkinter as tk
        from tkinter import filedialog, ttk

        self.root = root
        self.orchestrator = orchestrator
        self._tk = tk
        self._mobile: MobileSession | None = None
        self.workspace = tk.StringVar(value="")
        self.status = tk.StringVar(value="Ready.")
        self.capability = tk.StringVar(value="READY")
        self.mobile_status = tk.StringVar(value="Mobile access is off")
        root.title("ChatMPD — Local autonomous assistant")
        root.geometry("1040x780")
        root.minsize(760, 620)
        root.protocol("WM_DELETE_WINDOW", self._close)
        self._apply_icon()
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("App.TFrame", background="#0b0b0b")
        style.configure("App.TLabel", background="#0b0b0b", foreground="#f2f2f2")
        style.configure("Muted.TLabel", background="#0b0b0b", foreground="#a9a9a9")
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        root.configure(background="#0b0b0b")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        shell = ttk.Frame(root, padding=20, style="App.TFrame")
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(3, weight=1)
        self._shell = shell

        header = ttk.Frame(shell, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.columnconfigure(1, weight=1)
        self._brand_image = self._load_brand_image(58)
        if self._brand_image is not None:
            ttk.Label(header, image=self._brand_image, style="App.TLabel").grid(
                row=0, column=0, rowspan=2, padx=(0, 12)
            )
        ttk.Label(header, text="ChatMPD", font=("Segoe UI", 24, "bold"), style="App.TLabel").grid(
            row=0, column=1, sticky="w"
        )
        ttk.Label(header, text="One request. Local models. Verified execution.", style="Muted.TLabel").grid(
            row=1, column=1, sticky="w"
        )
        ttk.Label(header, textvariable=self.capability, style="App.TLabel").grid(
            row=0, column=2, rowspan=2, sticky="e"
        )

        project = ttk.Frame(shell, style="App.TFrame")
        project.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        project.columnconfigure(1, weight=1)
        ttk.Label(project, text="Project (optional)", style="Muted.TLabel").grid(row=0, column=0, padx=(0, 8))
        self.workspace_entry = ttk.Entry(project, textvariable=self.workspace)
        self.workspace_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(
            project,
            text="Choose folder",
            command=lambda: self._choose_folder(filedialog.askdirectory(parent=root, mustexist=True)),
        ).grid(row=0, column=2, padx=(8, 0))

        mobile = ttk.Frame(shell, style="App.TFrame")
        mobile.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        mobile.columnconfigure(0, weight=1)
        ttk.Label(mobile, textvariable=self.mobile_status, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.mobile_button = ttk.Button(mobile, text="Start mobile access", command=self._toggle_mobile)
        self.mobile_button.grid(row=0, column=1, sticky="e")

        self.output = tk.Text(
            shell, wrap="word", state="disabled", background="#101010",
            foreground="#f2f2f2", insertbackground="#f2f2f2",
            relief="flat", padx=16, pady=14, font=("Segoe UI", 11),
        )
        self.output.grid(row=3, column=0, sticky="nsew", pady=(0, 12))
        self.output.tag_configure("heading", font=("Segoe UI", 10, "bold"), foreground="#f08a55")
        self.output.tag_configure("muted", foreground="#a9a9a9")

        compose = ttk.Frame(shell, style="App.TFrame")
        compose.grid(row=4, column=0, sticky="ew")
        compose.columnconfigure(0, weight=1)
        self.prompt = tk.Text(
            compose, height=5, wrap="word", background="#151515",
            foreground="#f2f2f2", insertbackground="#f2f2f2",
            relief="flat", padx=12, pady=10, font=("Segoe UI", 11),
        )
        self.prompt.grid(row=0, column=0, sticky="ew")
        self.send_button = ttk.Button(
            compose, text="Run with ChatMPD", command=self._send, style="Accent.TButton"
        )
        self.send_button.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        ttk.Label(shell, textvariable=self.status, style="Muted.TLabel").grid(
            row=5, column=0, sticky="ew", pady=(10, 0)
        )
        self.controller = UniversalController(
            command_handler=orchestrator.command,
            schedule=lambda callback: root.after(0, callback),
            publish=self._publish,
        )
        root.bind("<Control-Return>", lambda _event: self._send() or "break")
        root.bind("<Control-l>", lambda _event: self.prompt.focus_set() or "break")
        self._publish(UniversalSnapshot(False, "Ready.", "ready", "ChatMPD is ready for any local task."))

    def _load_brand_image(self, size: int) -> Any | None:
        try:
            image = self._tk.PhotoImage(file=str(asset_path("chatmpd-192.png")))
            factor = max(1, 192 // max(1, size))
            return image.subsample(factor, factor) if factor > 1 else image
        except Exception:
            return None

    def _apply_icon(self) -> None:
        try:
            self._window_icon = self._tk.PhotoImage(file=str(asset_path("chatmpd-192.png")))
            self.root.iconphoto(True, self._window_icon)
        except Exception:
            self._window_icon = None

    def _choose_folder(self, selected: str) -> None:
        if selected:
            self.workspace.set(selected)
            self.status.set("Project folder selected; specialist and chat requests can still run without it.")
            self.prompt.focus_set()

    def _send(self) -> str:
        text = self.prompt.get("1.0", "end-1c").strip()
        if not text:
            self.status.set("Describe what you want ChatMPD to do.")
            self.prompt.focus_set()
            return "break"
        if self.controller.busy:
            self.status.set("ChatMPD is already working locally.")
            return "break"
        self._append("YOU\n", "heading")
        self._append(text + "\n\n")
        if self.controller.start(text, self.workspace.get()):
            self.prompt.delete("1.0", "end")
        return "break"

    def _publish(self, snapshot: UniversalSnapshot) -> None:
        self.status.set(snapshot.status)
        self.capability.set(snapshot.capability.upper())
        self.send_button.configure(state="disabled" if snapshot.busy else "normal")
        if snapshot.busy:
            self._append("CHATMPD\n", "heading")
            self._append("Working locally and selecting the appropriate capability...\n\n", "muted")
            return
        if snapshot.message:
            self._append(f"CHATMPD · {snapshot.capability.upper()}\n", "heading")
            self._append(snapshot.message + "\n")
            if snapshot.details:
                detail = json.dumps(snapshot.details, indent=2, ensure_ascii=False, default=str)
                self._append(detail + "\n", "muted")
            self._append("\n")

    def _append(self, text: str, tag: str | None = None) -> None:
        self.output.configure(state="normal")
        if tag:
            self.output.insert("end", text, tag)
        else:
            self.output.insert("end", text)
        self.output.configure(state="disabled")
        self.output.see("end")

    def _toggle_mobile(self) -> None:
        if self._mobile is not None:
            self._mobile.gateway.stop()
            self._mobile = None
            self.mobile_status.set("Mobile access is off")
            self.mobile_button.configure(text="Start mobile access")
            return
        try:
            self._mobile = start_mobile_session(self.orchestrator)
        except Exception as error:
            self.mobile_status.set(f"Mobile access could not start: {error}")
            return
        self.mobile_status.set(
            f"Mobile: {self._mobile.url}  ·  Pairing code: {self._mobile.pairing_code}"
        )
        self.mobile_button.configure(text="Stop mobile access")

    def _close(self) -> None:
        if self.controller.busy:
            self.status.set("ChatMPD must finish the current operation before closing safely.")
            return
        if self._mobile is not None:
            self._mobile.gateway.stop()
            self._mobile = None
        self.orchestrator.close()
        self.root.destroy()


def launch_universal_gui(orchestrator: ChatMPDOrchestrator) -> None:
    import tkinter as tk

    root = tk.Tk()
    UniversalWindow(root, orchestrator)
    root.mainloop()
