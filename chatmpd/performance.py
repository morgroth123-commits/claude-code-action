"""Evidence-based performance analysis and reversible optimization for Vader."""

from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any, Callable
from uuid import uuid4

from .activity import ActivityLog
from .host_policy import HostAction
from .permissions import PermissionProfileStore
from .platform_db import PlatformDatabase
from .system_capability import SystemInspector

BALANCED_GUID = "381b4222-f694-41f0-9685-ff5bb260df2e"
HIGH_PERFORMANCE_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"


def _clamp(value: float) -> int:
    return max(0, min(100, int(round(value))))


@dataclass(frozen=True)
class ProcessPressure:
    name: str
    pid: int
    cpu_percent: float
    memory_bytes: int
    io_bytes_per_sec: float = 0.0

@dataclass(frozen=True)
class PerformanceEvidence:
    cpu_percent: float
    memory_total_bytes: int
    memory_available_bytes: int
    disk_total_bytes: int
    disk_free_bytes: int
    gpu: dict[str, Any]
    processes: tuple[ProcessPressure, ...]
    power_plan_guid: str
    power_plan_name: str
    workloads: tuple[str, ...]
    commit_percent: float = 0.0
    pagefile_percent: float = 0.0
    disk_active_percent: float = 0.0
    disk_queue_length: float = 0.0
    disk_bytes_per_sec: float = 0.0
    gaming_config: dict[str, str] = field(default_factory=dict)
    startup_count: int = 0
    disk_health: tuple[str, ...] = ()


@dataclass(frozen=True)
class PerformanceFinding:
    key: str
    severity: str
    summary: str
    value: float


@dataclass(frozen=True)
class PerformanceRecommendation:
    key: str
    title: str
    detail: str
    priority: str
    action_mode: str | None = None


@dataclass(frozen=True)
class PerformanceReport:
    report_id: str
    created_at: str
    overall_score: int
    gaming_score: int
    ai_score: int
    balanced_score: int
    bottleneck: str
    telemetry_confidence: float
    evidence: PerformanceEvidence
    findings: tuple[PerformanceFinding, ...]
    top_processes: tuple[ProcessPressure, ...]
    recommendations: tuple[PerformanceRecommendation, ...]

class PerformanceStore:
    def __init__(self, database: PlatformDatabase | None = None) -> None:
        self.database = database or PlatformDatabase()

    def save(self, report: PerformanceReport) -> PerformanceReport:
        payload = json.dumps(asdict(report), ensure_ascii=False, default=str)
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO platform_records(namespace, record_id, payload, updated_at) VALUES (?, ?, ?, ?)",
                ("performance-report", report.report_id, payload, report.created_at),
            )
            connection.commit()
        return report

    def list(self, *, limit: int = 50) -> tuple[PerformanceReport, ...]:
        bounded = max(1, min(int(limit), 500))
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? ORDER BY updated_at DESC LIMIT ?",
                ("performance-report", bounded),
            ).fetchall()
        return tuple(self._decode(str(row["payload"])) for row in rows)

    @staticmethod
    def _decode(payload: str) -> PerformanceReport:
        data = json.loads(payload)
        evidence_data = dict(data["evidence"])
        evidence_data["processes"] = tuple(ProcessPressure(**item) for item in evidence_data.get("processes", ()))
        evidence_data["workloads"] = tuple(evidence_data.get("workloads", ()))
        evidence_data["gaming_config"] = dict(evidence_data.get("gaming_config") or {})
        evidence_data["disk_health"] = tuple(evidence_data.get("disk_health") or ())
        return PerformanceReport(
            report_id=str(data["report_id"]),
            created_at=str(data["created_at"]),
            overall_score=int(data["overall_score"]),
            gaming_score=int(data["gaming_score"]),
            ai_score=int(data["ai_score"]),
            balanced_score=int(data["balanced_score"]),
            bottleneck=str(data["bottleneck"]),
            telemetry_confidence=float(data["telemetry_confidence"]),
            evidence=PerformanceEvidence(**evidence_data),
            findings=tuple(PerformanceFinding(**item) for item in data.get("findings", ())),
            top_processes=tuple(ProcessPressure(**item) for item in data.get("top_processes", ())),
            recommendations=tuple(PerformanceRecommendation(**item)
                                  for item in data.get("recommendations", ())),
        )


class PerformanceAnalyzer:
    def __init__(
        self,
        store: PerformanceStore | None = None,
        *,
        evidence_probe: Callable[[], PerformanceEvidence] | None = None,
    ) -> None:
        self.store = store or PerformanceStore()
        self._probe = evidence_probe or collect_performance_evidence

    def analyze(self) -> PerformanceReport:
        evidence = self._probe()
        components, confidence = self._components(evidence)
        gaming = _clamp(.22 * components["cpu"] + .18 * components["memory"] +
                        .08 * components["commit"] + .27 * components["gpu"] +
                        .15 * components["vram"] + .10 * components["disk"])
        ai = _clamp(.12 * components["cpu"] + .18 * components["memory"] +
                    .15 * components["commit"] + .18 * components["gpu"] +
                    .27 * components["vram"] + .10 * components["disk"])
        balanced = _clamp(.28 * components["cpu"] + .22 * components["memory"] +
                          .10 * components["commit"] + .15 * components["gpu"] +
                          .10 * components["vram"] + .15 * components["disk"])
        overall = _clamp((gaming + ai + balanced) / 3)
        available = {key: value for key, value in components.items()
                     if key not in {"gpu", "vram"} or evidence.gpu}
        if available:
            lowest = min(available, key=available.get)
            bottleneck = lowest if available[lowest] < 35.0 else "none"
        else:
            bottleneck = "unknown"
        findings = self._findings(components, evidence)
        recommendations = self._recommendations(findings, evidence, bottleneck)
        top = tuple(sorted(
            evidence.processes,
            key=lambda item: (
                item.cpu_percent
                + min(100.0, item.memory_bytes / (1024 ** 3) * 10.0)
                + min(100.0, item.io_bytes_per_sec / (1024 ** 2))
            ),
            reverse=True,
        )[:8])
        report = PerformanceReport(
            report_id=uuid4().hex,
            created_at=datetime.now(UTC).isoformat(),
            overall_score=overall,
            gaming_score=gaming,
            ai_score=ai,
            balanced_score=balanced,
            bottleneck=bottleneck,
            telemetry_confidence=confidence,
            evidence=evidence,
            findings=findings,
            top_processes=top,
            recommendations=recommendations,
        )
        return self.store.save(report)

    @staticmethod
    def _components(evidence: PerformanceEvidence) -> tuple[dict[str, float], float]:
        memory = (100.0 * evidence.memory_available_bytes / evidence.memory_total_bytes
                  if evidence.memory_total_bytes else 50.0)
        free_percent = (100.0 * evidence.disk_free_bytes / evidence.disk_total_bytes
                        if evidence.disk_total_bytes else 25.0)
        capacity = min(100.0, free_percent * 4.0)
        disk_idle = max(0.0, 100.0 - float(evidence.disk_active_percent))
        queue_headroom = max(0.0, 100.0 - 20.0 * float(evidence.disk_queue_length))
        disk = .20 * capacity + .50 * disk_idle + .30 * queue_headroom
        pressure_known = evidence.commit_percent > 0 or evidence.pagefile_percent > 0
        commit = min(100.0 - float(evidence.commit_percent),
                     100.0 - float(evidence.pagefile_percent)) if pressure_known else memory
        gpu_present = bool(evidence.gpu)
        gpu = 100.0 - float(evidence.gpu.get("utilization_percent", 40.0)) if gpu_present else 60.0
        total_vram = float(evidence.gpu.get("vram_total_mib", 0.0)) if gpu_present else 0.0
        used_vram = float(evidence.gpu.get("vram_used_mib", 0.0)) if gpu_present else 0.0
        vram = 100.0 * max(0.0, total_vram - used_vram) / total_vram if total_vram else 60.0
        components = {
            "cpu": max(0.0, 100.0 - float(evidence.cpu_percent)),
            "memory": max(0.0, min(100.0, memory)),
            "commit": max(0.0, min(100.0, commit)),
            "disk": max(0.0, min(100.0, disk)),
            "gpu": max(0.0, min(100.0, gpu)),
            "vram": max(0.0, min(100.0, vram)),
        }
        confidence = 1.0 if gpu_present else 0.6
        return components, confidence

    @staticmethod
    def _findings(
        components: dict[str, float], evidence: PerformanceEvidence
    ) -> tuple[PerformanceFinding, ...]:
        labels = {
            "cpu": "CPU headroom is low.",
            "memory": "Available system memory is low.",
            "commit": "Committed memory or pagefile pressure is high.",
            "disk": "Disk activity or queue pressure is high.",
            "gpu": "GPU utilization leaves little headroom.",
            "vram": "GPU VRAM headroom is low.",
        }
        findings: list[PerformanceFinding] = []
        for key, value in components.items():
            if key in {"gpu", "vram"} and not evidence.gpu:
                continue
            if value < 25:
                severity = "high" if value < 10 else "medium"
                findings.append(PerformanceFinding(key, severity, labels[key], round(value, 1)))
        if evidence.startup_count >= 30:
            findings.append(PerformanceFinding(
                "startup", "medium",
                "Many startup entries can add background contention after sign-in.",
                float(evidence.startup_count),
            ))
        unhealthy = [item for item in evidence.disk_health
                     if any(word in item.casefold() for word in ("warning", "degraded", "unhealthy", "error", "failed"))]
        if unhealthy:
            findings.append(PerformanceFinding(
                "disk-health", "high",
                "Windows reports a physical disk health or operational warning.",
                float(len(unhealthy)),
            ))
        return tuple(findings)

    @staticmethod
    def _recommendations(
        findings: tuple[PerformanceFinding, ...],
        evidence: PerformanceEvidence,
        bottleneck: str,
    ) -> tuple[PerformanceRecommendation, ...]:
        recommendations: list[PerformanceRecommendation] = []
        workloads = {item.casefold() for item in evidence.workloads}
        if "eso" in workloads and evidence.power_plan_guid.casefold() != HIGH_PERFORMANCE_GUID:
            recommendations.append(PerformanceRecommendation(
                "profile", "Use Gaming mode while ESO is active",
                "Gaming mode uses the Windows High performance plan and releases ChatMPD-owned model resources so they do not compete with the game.",
                "high", "gaming",
            ))
        elif workloads.intersection({"chatmpd", "llama.cpp", "lm-studio", "bionic"}) and evidence.power_plan_guid.casefold() != HIGH_PERFORMANCE_GUID:
            recommendations.append(PerformanceRecommendation(
                "profile", "Use AI / ChatMPD mode for local inference",
                "AI mode uses the Windows High performance plan while keeping ChatMPD's existing model and GPU coordination rules intact.",
                "medium", "ai",
            ))

        finding_keys = {item.key for item in findings}
        if finding_keys.intersection({"memory", "commit"}):
            recommendations.append(PerformanceRecommendation(
                "memory", "Reduce memory pressure",
                "Pause or close nonessential high-memory applications shown below. ChatMPD will not close unrelated applications automatically.",
                "high" if bottleneck in {"memory", "commit"} else "medium",
            ))
        if "cpu" in finding_keys:
            recommendations.append(PerformanceRecommendation(
                "cpu", "Reduce CPU contention",
                "Pause or close nonessential high-CPU applications shown below; leave foreground game and ChatMPD work you still need running.",
                "high" if bottleneck == "cpu" else "medium",
            ))
        if finding_keys.intersection({"gpu", "vram"}):
            recommendations.append(PerformanceRecommendation(
                "vram", "Free GPU headroom",
                "Unload optional local AI/media workloads before gaming or heavy generation. ChatMPD releases its own managed model resources when switching workloads.",
                "high" if bottleneck in {"gpu", "vram"} else "medium",
            ))
        if "disk" in finding_keys:
            recommendations.append(PerformanceRecommendation(
                "disk", "Reduce storage contention",
                "Pause nonessential high-I/O work shown below and let the active game or model workload finish before starting another large disk task.",
                "medium",
            ))
        if "startup" in finding_keys:
            recommendations.append(PerformanceRecommendation(
                "startup", "Review startup applications",
                "Windows reports many startup entries. Review them manually and disable only software you recognize and do not need at sign-in.",
                "low",
            ))
        if "disk-health" in finding_keys:
            recommendations.append(PerformanceRecommendation(
                "disk-health", "Protect data before tuning performance",
                "Back up important data and inspect Windows storage health. ChatMPD will not attempt automatic drive repair.",
                "high",
            ))
        if not recommendations:
            recommendations.append(PerformanceRecommendation(
                "healthy", "No urgent optimization needed",
                "Current telemetry shows healthy headroom. Keep the existing profile unless you intentionally want Gaming or AI mode.",
                "low",
            ))
        return tuple(recommendations)


class _FileTime(ctypes.Structure):
    _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]


def _filetime_value(value: _FileTime) -> int:
    return (int(value.high) << 32) | int(value.low)


def _cpu_percent(sample_seconds: float = 0.15) -> float:
    if os.name != "nt":
        return 0.0

    def sample() -> tuple[int, int, int]:
        idle, kernel, user = _FileTime(), _FileTime(), _FileTime()
        ok = ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        )
        if not ok:
            raise OSError("GetSystemTimes failed")
        return _filetime_value(idle), _filetime_value(kernel), _filetime_value(user)

    try:
        first = sample()
        time.sleep(max(0.05, min(float(sample_seconds), 0.5)))
        second = sample()
        idle_delta = second[0] - first[0]
        total_delta = (second[1] - first[1]) + (second[2] - first[2])
        if total_delta <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta))
    except (OSError, AttributeError):
        return 0.0

def _powershell_process_rows() -> list[dict[str, Any]]:
    command = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "Get-Process | Select-Object Id,ProcessName,CPU,WorkingSet64 | ConvertTo-Json -Compress",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=5, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return []
        data = json.loads(completed.stdout)
        rows = data if isinstance(data, list) else [data]
        return [dict(row) for row in rows if isinstance(row, dict)]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []


def parse_process_pressure_rows(rows: list[dict[str, Any]], *, logical_cpus: int | None = None) -> tuple[ProcessPressure, ...]:
    logical = max(1, int(logical_cpus or os.cpu_count() or 1))
    results: list[ProcessPressure] = []
    for row in rows:
        try:
            pid = int(row.get("IDProcess") or 0)
            if pid <= 0:
                continue
            name = re.sub(r"#\d+$", "", str(row.get("Name") or "unknown"))
            cpu = max(0.0, min(100.0, float(row.get("PercentProcessorTime") or 0) / logical))
            results.append(ProcessPressure(
                name, pid, cpu, int(row.get("WorkingSet") or 0),
                max(0.0, float(row.get("IODataBytesPersec") or 0)),
            ))
        except (TypeError, ValueError):
            continue
    return tuple(results)


def _process_probe(sample_seconds: float = 0.2) -> tuple[ProcessPressure, ...]:
    command = [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "Get-CimInstance Win32_PerfFormattedData_PerfProc_Process | "
        "Where-Object {$_.IDProcess -gt 0 -and $_.Name -ne '_Total'} | "
        "Select Name,IDProcess,PercentProcessorTime,WorkingSet,IODataBytesPersec | ConvertTo-Json -Compress",
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=8, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if completed.returncode != 0 or not completed.stdout.strip():
            return ()
        data = json.loads(completed.stdout)
        rows = data if isinstance(data, list) else [data]
        return parse_process_pressure_rows([dict(row) for row in rows if isinstance(row, dict)])
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return ()


def _gpu_probe() -> dict[str, Any]:
    command = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.total,memory.used,temperature.gpu,power.draw,power.limit,clocks.gr",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=4, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return {}
        parts = [part.strip() for part in completed.stdout.splitlines()[0].split(",")]
        if len(parts) != 7:
            return {}
        values = [float(part) for part in parts]
        return {
            "utilization_percent": values[0],
            "vram_total_mib": int(values[1]),
            "vram_used_mib": int(values[2]),
            "temperature_c": values[3],
            "power_w": values[4],
            "power_limit_w": values[5],
            "graphics_clock_mhz": values[6],
        }
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def _power_plan() -> tuple[str, str]:
    try:
        completed = subprocess.run(
            ["powercfg.exe", "/GETACTIVESCHEME"], capture_output=True, text=True,
            timeout=3, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = completed.stdout.strip()
        match = re.search(r"([0-9a-fA-F-]{36})(?:\s+\(([^)]+)\))?", text)
        if match:
            return match.group(1).casefold(), str(match.group(2) or "Unknown")
    except (OSError, subprocess.SubprocessError):
        pass
    return "", "Unknown"

def parse_windows_pressure_payload(payload: dict[str, Any]) -> dict[str, Any]:
    memory = dict(payload.get("memory") or {})
    disk = dict(payload.get("disk") or {})
    pagefiles = payload.get("pagefile") or ()
    if isinstance(pagefiles, dict):
        pagefiles = (pagefiles,)
    allocated = sum(float(item.get("AllocatedBaseSize") or 0) for item in pagefiles if isinstance(item, dict))
    used = sum(float(item.get("CurrentUsage") or 0) for item in pagefiles if isinstance(item, dict))
    game_mode = payload.get("game_mode")
    hags = payload.get("hags")
    gaming = {
        "game_mode": "enabled" if game_mode == 1 else "disabled" if game_mode == 0 else "default",
        "hags": "enabled" if hags == 2 else "disabled" if hags == 1 else "default",
    }
    disks = payload.get("physical_disks") or ()
    if isinstance(disks, dict):
        disks = (disks,)
    health = tuple(
        " · ".join(str(item.get(key) or "unknown") for key in
                   ("FriendlyName", "MediaType", "HealthStatus", "OperationalStatus"))
        for item in disks if isinstance(item, dict)
    )
    return {
        "commit_percent": max(0.0, min(100.0, float(memory.get("PercentCommittedBytesInUse") or 0))),
        "pagefile_percent": max(0.0, min(100.0, 100.0 * used / allocated)) if allocated else 0.0,
        "disk_active_percent": max(0.0, min(100.0, float(disk.get("PercentDiskTime") or 0))),
        "disk_queue_length": max(0.0, float(disk.get("CurrentDiskQueueLength") or 0)),
        "disk_bytes_per_sec": max(0.0, float(disk.get("DiskBytesPersec") or 0)),
        "gaming_config": gaming,
        "startup_count": max(0, int(payload.get("startup_count") or 0)),
        "disk_health": health,
    }


def _windows_pressure_probe() -> dict[str, Any]:
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "$m=Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory | Select PercentCommittedBytesInUse,PagesPersec; "
        "$d=Get-CimInstance Win32_PerfFormattedData_PerfDisk_PhysicalDisk | Where-Object Name -eq '_Total' | Select PercentDiskTime,CurrentDiskQueueLength,DiskBytesPersec; "
        "$p=Get-CimInstance Win32_PageFileUsage | Select AllocatedBaseSize,CurrentUsage; "
        "$gm=(Get-ItemProperty 'HKCU:\\Software\\Microsoft\\GameBar' -ErrorAction SilentlyContinue).AutoGameModeEnabled; "
        "$hags=(Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\GraphicsDrivers' -ErrorAction SilentlyContinue).HwSchMode; "
        "$startup=@(Get-CimInstance Win32_StartupCommand -ErrorAction SilentlyContinue).Count; "
        "$pd=@(Get-PhysicalDisk -ErrorAction SilentlyContinue | Select FriendlyName,MediaType,HealthStatus,OperationalStatus); "
        "[pscustomobject]@{memory=$m;disk=$d;pagefile=@($p);game_mode=$gm;hags=$hags;startup_count=$startup;physical_disks=$pd} | ConvertTo-Json -Depth 4 -Compress"]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=8, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if completed.returncode != 0 or not completed.stdout.strip():
            return {}
        data = json.loads(completed.stdout)
        return parse_windows_pressure_payload(data) if isinstance(data, dict) else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def collect_performance_evidence() -> PerformanceEvidence:
    system = SystemInspector(gpu_probe=lambda: {}).snapshot()
    processes = _process_probe()
    names = {item.name.casefold() for item in processes}
    workloads: list[str] = []
    workload_markers = {
        "eso": {"eso64"},
        "chatmpd": {"chatmpd"},
        "llama.cpp": {"llama-server"},
        "lm-studio": {"lm studio", "lm studio helper"},
        "bionic": {"bionic"},
    }
    for label, markers in workload_markers.items():
        if names.intersection(markers):
            workloads.append(label)
    power_guid, power_name = _power_plan()
    pressure = _windows_pressure_probe()
    return PerformanceEvidence(
        cpu_percent=_cpu_percent(),
        memory_total_bytes=system.memory_total_bytes,
        memory_available_bytes=system.memory_available_bytes,
        disk_total_bytes=system.disk_total_bytes,
        disk_free_bytes=system.disk_free_bytes,
        gpu=_gpu_probe(),
        processes=processes,
        power_plan_guid=power_guid,
        power_plan_name=power_name,
        workloads=tuple(workloads),
        commit_percent=float(pressure.get("commit_percent", 0.0)),
        pagefile_percent=float(pressure.get("pagefile_percent", 0.0)),
        disk_active_percent=float(pressure.get("disk_active_percent", 0.0)),
        disk_queue_length=float(pressure.get("disk_queue_length", 0.0)),
        disk_bytes_per_sec=float(pressure.get("disk_bytes_per_sec", 0.0)),
        gaming_config=dict(pressure.get("gaming_config") or {}),
        startup_count=int(pressure.get("startup_count", 0)),
        disk_health=tuple(pressure.get("disk_health") or ()),
    )


@dataclass(frozen=True)
class OptimizationResult:
    mode: str
    changed: bool
    power_plan_guid: str
    previous_power_plan_guid: str
    message: str
    created_at: str

class VaderOptimizer:
    def __init__(
        self,
        *,
        database: PlatformDatabase | None = None,
        permissions: PermissionProfileStore | None = None,
        activity: ActivityLog | None = None,
        power_getter: Callable[[], tuple[str, str]] = _power_plan,
        power_setter: Callable[[str], None] | None = None,
        release_runtime: Callable[[], None] | None = None,
    ) -> None:
        self.database = database or PlatformDatabase()
        self.permissions = permissions or PermissionProfileStore(self.database)
        self.activity = activity or ActivityLog(self.database)
        self._power_getter = power_getter
        self._power_setter = power_setter or self._set_power_plan
        self._release_runtime = release_runtime or (lambda: None)

    def bind_runtime(self, release_runtime: Callable[[], None]) -> None:
        self._release_runtime = release_runtime

    def apply(self, mode: str, *, confirmed: bool = False) -> OptimizationResult:
        clean = str(mode).strip().casefold()
        if clean not in {"analyze", "balanced", "gaming", "ai"}:
            raise ValueError("Performance mode must be analyze, balanced, gaming, or ai.")
        current_guid, current_name = self._power_getter()
        if clean == "analyze":
            return self._result(clean, False, current_guid, current_guid, "Analyze-only made no changes.")
        state = self._state()
        if not state.get("baseline_guid"):
            state["baseline_guid"] = current_guid
            state["baseline_name"] = current_name
        target = BALANCED_GUID if clean == "balanced" else HIGH_PERFORMANCE_GUID
        if clean == "gaming":
            self._release_runtime()
        changed = bool(target and target.casefold() != current_guid.casefold())
        if changed:
            decision = self.permissions.evaluate(HostAction("system", "set", "Windows power plan"))
            if decision.requires_confirmation and not confirmed:
                raise PermissionError(decision.reason)
            self._power_setter(target)
        state["active_mode"] = clean
        self._write_state(state)
        message = f"Applied {clean} performance mode."
        result = self._result(clean, changed, target or current_guid, current_guid, message)
        self.activity.record("performance", message, details={
            "mode": clean, "changed": changed, "from_power_plan": current_guid,
            "to_power_plan": target or current_guid,
        })
        return result

    def restore(self, *, confirmed: bool = False) -> OptimizationResult:
        current_guid, _ = self._power_getter()
        state = self._state()
        baseline = str(state.get("baseline_guid") or current_guid)
        changed = bool(baseline and baseline.casefold() != current_guid.casefold())
        if changed:
            decision = self.permissions.evaluate(HostAction("system", "set", "Windows power plan"))
            if decision.requires_confirmation and not confirmed:
                raise PermissionError(decision.reason)
            self._power_setter(baseline)
        state["active_mode"] = "restored"
        state["baseline_guid"] = ""
        state["baseline_name"] = ""
        self._write_state(state)
        result = self._result("restored", changed, baseline, current_guid, "Restored captured performance baseline.")
        self.activity.record("performance", result.message, details={
            "changed": changed, "from_power_plan": current_guid, "to_power_plan": baseline,
        })
        return result

    def status(self) -> dict[str, Any]:
        current_guid, current_name = self._power_getter()
        state = self._state()
        return {
            "active_mode": str(state.get("active_mode") or "balanced"),
            "baseline_guid": str(state.get("baseline_guid") or ""),
            "baseline_name": str(state.get("baseline_name") or ""),
            "current_power_plan_guid": current_guid,
            "current_power_plan_name": current_name,
        }
    def _state(self) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT payload FROM platform_records WHERE namespace=? AND record_id=?",
                ("performance-state", "optimizer"),
            ).fetchone()
        if row is None:
            return {}
        try:
            data = json.loads(str(row["payload"]))
            return dict(data) if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _write_state(self, state: dict[str, Any]) -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO platform_records(namespace, record_id, payload, updated_at) VALUES (?, ?, ?, ?)",
                ("performance-state", "optimizer", json.dumps(state), now),
            )
            connection.commit()

    @staticmethod
    def _set_power_plan(guid: str) -> None:
        completed = subprocess.run(
            ["powercfg.exe", "/SETACTIVE", str(guid)], capture_output=True, text=True,
            timeout=5, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or "powercfg failed").strip()[:500])

    @staticmethod
    def _result(mode: str, changed: bool, target: str, previous: str, message: str) -> OptimizationResult:
        return OptimizationResult(
            mode, bool(changed), str(target), str(previous), str(message), datetime.now(UTC).isoformat()
        )


class AdaptivePerformanceController:
    def __init__(
        self, optimizer: Any, *, workload_probe: Callable[[], bool], base_mode: str = "balanced"
    ) -> None:
        self.optimizer = optimizer
        self._workload_probe = workload_probe
        self.base_mode = str(base_mode).strip().casefold()
        self._last_mode: str | None = None

    @property
    def current_mode(self) -> str | None:
        return self._last_mode

    def tick(self) -> str:
        mode = "gaming" if bool(self._workload_probe()) else self.base_mode
        if mode != self._last_mode:
            self.optimizer.apply(mode)
            self._last_mode = mode
        return mode


def _eso_running() -> bool:
    try:
        completed = subprocess.run(
            ["tasklist.exe", "/FI", "IMAGENAME eq eso64.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=3, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return '"eso64.exe"' in completed.stdout.casefold()
    except (OSError, subprocess.SubprocessError):
        return False


class PerformanceCenter:
    def __init__(
        self,
        analyzer: PerformanceAnalyzer,
        optimizer: VaderOptimizer,
        *,
        workload_probe: Callable[[], bool] = _eso_running,
        poll_seconds: float = 30.0,
    ) -> None:
        self.analyzer = analyzer
        self.optimizer = optimizer
        self._workload_probe = workload_probe
        self._poll_seconds = max(5.0, min(float(poll_seconds), 300.0))
        self._adaptive_enabled = False
        self._base_mode = "balanced"
        self._controller = AdaptivePerformanceController(
            optimizer, workload_probe=workload_probe, base_mode=self._base_mode
        )
        self._last_optimization: dict[str, Any] | None = None
        self._stop = Event()
        self._thread: Thread | None = None
    def analyze(self) -> PerformanceReport:
        return self.analyzer.analyze()

    def history(self, *, limit: int = 50) -> tuple[PerformanceReport, ...]:
        return self.analyzer.store.list(limit=limit)

    def apply(self, mode: str, *, confirmed: bool = False) -> OptimizationResult:
        clean = str(mode).strip().casefold()
        before = self.analyze() if clean != "analyze" else None
        if clean != "gaming":
            self._base_mode = clean if clean in {"balanced", "ai"} else self._base_mode
        result = self.optimizer.apply(clean, confirmed=confirmed)
        if before is not None:
            after = self.analyze()
            self._last_optimization = {
                "mode": clean, "before_report_id": before.report_id,
                "after_report_id": after.report_id,
                "before_score": before.overall_score, "after_score": after.overall_score,
                "score_delta": after.overall_score - before.overall_score,
            }
        return result

    def optimize_current(self, *, confirmed: bool = False) -> OptimizationResult:
        before = self.analyze()
        workloads = {str(item).casefold() for item in before.evidence.workloads}
        if "eso" in workloads or bool(self._workload_probe()):
            mode = "gaming"
        elif workloads.intersection({"chatmpd", "llama.cpp", "lm-studio", "bionic"}):
            mode = "ai"
        else:
            mode = "balanced"
        if mode != "gaming":
            self._base_mode = mode
        result = self.optimizer.apply(mode, confirmed=confirmed)
        after = self.analyze()
        self._last_optimization = {
            "mode": mode, "before_report_id": before.report_id,
            "after_report_id": after.report_id,
            "before_score": before.overall_score, "after_score": after.overall_score,
            "score_delta": after.overall_score - before.overall_score,
            "automatic": True,
        }
        return result

    def restore(self, *, confirmed: bool = False) -> OptimizationResult:
        self._base_mode = "balanced"
        return self.optimizer.restore(confirmed=confirmed)

    def bind_runtime(self, release_runtime: Callable[[], None]) -> None:
        self.optimizer.bind_runtime(release_runtime)

    def status(self) -> dict[str, Any]:
        return {
            **self.optimizer.status(),
            "adaptive_enabled": self._adaptive_enabled,
            "adaptive_base_mode": self._base_mode,
            "history_count": len(self.history(limit=500)),
            "last_optimization": self._last_optimization,
        }

    def set_adaptive(
        self, enabled: bool, *, base_mode: str = "balanced", start_thread: bool = True
    ) -> dict[str, Any]:
        clean_base = str(base_mode).strip().casefold()
        if clean_base not in {"balanced", "ai"}:
            raise ValueError("Adaptive base mode must be balanced or ai.")
        if not enabled:
            previous_mode = self._controller.current_mode
            self._adaptive_enabled = False
            if previous_mode == "gaming":
                self.optimizer.apply(self._base_mode)
            self._stop_thread()
            return self.status()
        self._base_mode = clean_base
        self._controller = AdaptivePerformanceController(
            self.optimizer, workload_probe=self._workload_probe, base_mode=clean_base
        )
        self._adaptive_enabled = True
        self.tick_adaptive()
        if start_thread and (self._thread is None or not self._thread.is_alive()):
            self._stop.clear()
            self._thread = Thread(
                target=self._adaptive_loop,
                name="ChatMPD performance adaptive controller",
                daemon=True,
            )
            self._thread.start()
        return self.status()

    def tick_adaptive(self) -> str:
        if not self._adaptive_enabled:
            return self._base_mode
        return self._controller.tick()

    def close(self) -> None:
        self._adaptive_enabled = False
        self._stop_thread()

    def _adaptive_loop(self) -> None:
        while not self._stop.wait(self._poll_seconds):
            if not self._adaptive_enabled:
                return
            try:
                self.tick_adaptive()
            except Exception as error:
                activity = getattr(self.optimizer, "activity", None)
                if activity is not None:
                    activity.record(
                        "performance", "Adaptive performance check failed.",
                        details={"error": f"{type(error).__name__}: {error}"[:300]},
                    )

    def _stop_thread(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
