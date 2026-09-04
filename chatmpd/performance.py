"""Evidence-based performance analysis and reversible optimization for Vader."""

from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .activity import ActivityLog
from .host_policy import HostAction
from .permissions import PermissionProfileStore
from .platform_db import PlatformDatabase
from .system_capability import SystemInspector

HIGH_PERFORMANCE_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"


def _clamp(value: float) -> int:
    return max(0, min(100, int(round(value))))


@dataclass(frozen=True)
class ProcessPressure:
    name: str
    pid: int
    cpu_percent: float
    memory_bytes: int

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


@dataclass(frozen=True)
class PerformanceFinding:
    key: str
    severity: str
    summary: str
    value: float


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
        return PerformanceReport(            report_id=str(data["report_id"]),
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
        gaming = _clamp(.25 * components["cpu"] + .20 * components["memory"] +
                        .30 * components["gpu"] + .15 * components["vram"] + .10 * components["storage"])
        ai = _clamp(.15 * components["cpu"] + .20 * components["memory"] +
                    .20 * components["gpu"] + .35 * components["vram"] + .10 * components["storage"])
        balanced = _clamp(.30 * components["cpu"] + .30 * components["memory"] +
                          .15 * components["gpu"] + .10 * components["vram"] + .15 * components["storage"])
        overall = _clamp((gaming + ai + balanced) / 3)
        available = {key: value for key, value in components.items()
                     if key not in {"gpu", "vram"} or evidence.gpu}
        bottleneck = min(available, key=available.get) if available else "unknown"
        findings = self._findings(components, evidence)
        top = tuple(sorted(
            evidence.processes,
            key=lambda item: (item.cpu_percent, item.memory_bytes),
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
        )
        return self.store.save(report)

    @staticmethod
    def _components(evidence: PerformanceEvidence) -> tuple[dict[str, float], float]:
        memory = (100.0 * evidence.memory_available_bytes / evidence.memory_total_bytes
                  if evidence.memory_total_bytes else 50.0)
        free_percent = (100.0 * evidence.disk_free_bytes / evidence.disk_total_bytes
                        if evidence.disk_total_bytes else 25.0)
        storage = min(100.0, free_percent * 4.0)
        gpu_present = bool(evidence.gpu)
        gpu = 100.0 - float(evidence.gpu.get("utilization_percent", 40.0)) if gpu_present else 60.0
        total_vram = float(evidence.gpu.get("vram_total_mib", 0.0)) if gpu_present else 0.0
        used_vram = float(evidence.gpu.get("vram_used_mib", 0.0)) if gpu_present else 0.0
        vram = 100.0 * max(0.0, total_vram - used_vram) / total_vram if total_vram else 60.0
        components = {
            "cpu": max(0.0, 100.0 - float(evidence.cpu_percent)),
            "memory": max(0.0, min(100.0, memory)),
            "storage": max(0.0, min(100.0, storage)),
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
            "storage": "System drive free-space headroom is low.",
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
        return tuple(findings)

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


def _process_probe(sample_seconds: float = 0.2) -> tuple[ProcessPressure, ...]:
    first = {int(row.get("Id", -1)): row for row in _powershell_process_rows()}
    started = time.monotonic()
    time.sleep(max(0.05, min(float(sample_seconds), 0.5)))
    second_rows = _powershell_process_rows()
    elapsed = max(0.05, time.monotonic() - started)
    logical = max(1, int(os.cpu_count() or 1))
    results: list[ProcessPressure] = []
    for row in second_rows:
        try:
            pid = int(row.get("Id", 0))
            current_cpu = float(row.get("CPU") or 0.0)
            previous_cpu = float(first.get(pid, {}).get("CPU") or current_cpu)
            cpu = max(0.0, min(100.0, 100.0 * (current_cpu - previous_cpu) / elapsed / logical))
            results.append(ProcessPressure(str(row.get("ProcessName") or "unknown"), pid, cpu,
                                           int(row.get("WorkingSet64") or 0)))
        except (TypeError, ValueError):
            continue
    return tuple(results)

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
        target = str(state.get("baseline_guid") or current_guid) if clean == "balanced" else HIGH_PERFORMANCE_GUID
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
        state["active_mode"] = "balanced"
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
    def tick(self) -> str:
        mode = "gaming" if bool(self._workload_probe()) else self.base_mode
        if mode != self._last_mode:
            self.optimizer.apply(mode)
            self._last_mode = mode
        return mode
