"""Bounded read-only host diagnostics for ChatMPD."""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class SystemSnapshot:
    os_name: str
    os_release: str
    machine: str
    cpu_logical: int
    memory_total_bytes: int
    memory_available_bytes: int
    disk_total_bytes: int
    disk_free_bytes: int
    gpu: dict[str, Any]


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _memory_probe() -> tuple[int, int]:
    if os.name != "nt":
        return 0, 0
    status = _MemoryStatus()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return 0, 0
    return int(status.ullTotalPhys), int(status.ullAvailPhys)


def _gpu_probe() -> dict[str, Any]:
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=4, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if completed.returncode != 0 or not completed.stdout.strip():
        return {}
    parts = [part.strip() for part in completed.stdout.splitlines()[0].split(",")]
    if len(parts) != 3:
        return {}
    try:
        return {
            "name": parts[0],
            "vram_total_mib": int(parts[1]),
            "vram_used_mib": int(parts[2]),
        }
    except ValueError:
        return {"name": parts[0]}


class SystemInspector:
    def __init__(
        self,
        *,
        disk_root: Path | None = None,
        memory_probe: Callable[[], tuple[int, int]] = _memory_probe,
        gpu_probe: Callable[[], dict[str, Any]] = _gpu_probe,
    ) -> None:
        self.disk_root = Path(disk_root or Path.home().anchor or Path.home())
        self._memory_probe = memory_probe
        self._gpu_probe = gpu_probe

    def snapshot(self) -> SystemSnapshot:
        total_memory, available_memory = self._memory_probe()
        disk = shutil.disk_usage(self.disk_root)
        return SystemSnapshot(
            os_name=platform.system(),
            os_release=platform.release(),
            machine=platform.machine(),
            cpu_logical=max(1, int(os.cpu_count() or 1)),
            memory_total_bytes=int(total_memory),
            memory_available_bytes=int(available_memory),
            disk_total_bytes=int(disk.total),
            disk_free_bytes=int(disk.free),
            gpu=dict(self._gpu_probe()),
        )
