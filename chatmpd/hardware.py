"""Read-only hardware profiling and local model tier recommendations."""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import asdict, dataclass
from typing import Callable


@dataclass(frozen=True)
class HardwareProfile:
    os_name: str
    cpu_logical: int
    memory_total_gib: float
    gpu_name: str
    gpu_vram_gib: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def recommend_model_tier(profile: HardwareProfile) -> str:
    if profile.gpu_vram_gib >= 16 or profile.memory_total_gib >= 48:
        return "large"
    if profile.gpu_vram_gib >= 8 and profile.memory_total_gib >= 24:
        return "medium"
    return "small"

def detect_hardware(
    *,
    gpu_probe: Callable[[], tuple[str, float]] | None = None,
) -> HardwareProfile:
    memory_gib = 0.0
    try:
        import psutil
        memory_gib = psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        if os.name == "nt":
            import ctypes
            class _MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                memory_gib = status.ullTotalPhys / (1024 ** 3)
    if gpu_probe is None:
        gpu_probe = _default_gpu_probe
    gpu_name, gpu_vram = gpu_probe()
    return HardwareProfile(
        platform.platform(), os.cpu_count() or 1, round(memory_gib, 1),
        gpu_name, round(gpu_vram, 1),
    )

def _default_gpu_probe() -> tuple[str, float]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        first = (result.stdout or "").splitlines()[0]
        name, raw_mb = [part.strip() for part in first.rsplit(",", 1)]
        return name, float(raw_mb) / 1024.0
    except Exception:
        return "Unknown / integrated", 0.0
