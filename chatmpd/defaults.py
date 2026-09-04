"""Production assembly for Vader's local ChatMPD capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from .assistant import DesktopAssistant
from .comfyui import ComfyUIBackend, ComfyUIClient
from .eso import EsoAddonManager
from .llamacpp import LlamaCppProvider
from .media import MediaPipeline, normalize_media_request
from .media_runtime import MediaRuntime
from .ltxvideo import FFmpegAssembler, LTXVideoWorkflowBuilder, plan_video_segments
from .model_registry import LocalModel, ModelRegistry
from .model_runtime import ModelRuntimeManager
from .orchestrator import ChatMPDOrchestrator
from .platform_services import build_platform_services
from .runtime import LlamaCppRuntime, RuntimeConfig
from .system_capability import SystemInspector
from .vortex import VortexInventory
from .zimage import ZImageWorkflowBuilder


DEFAULT_MODEL_ROOTS = (
    Path(r"D:\ChatMPD\models\huggingface"),
    Path.home() / ".cache" / "huggingface" / "hub",
)


def eso_scan_summary(report: Any) -> dict[str, Any]:
    issues = []
    for issue in tuple(report.issues)[:50]:
        issues.append({
            "code": issue.code, "severity": issue.severity,
            "addon_id": issue.addon_id, "message": issue.message,
        })
    return {
        "summary": (
            f"ESO scan: {len(report.manifests)} addons, "
            f"{report.critical_count} critical, {report.warning_count} warnings."
        ),
        "addon_count": len(report.manifests),
        "current_api": report.current_api,
        "critical_count": report.critical_count,
        "warning_count": report.warning_count,
        "repairable_count": report.repairable_count,
        "scanned_at": report.scanned_at,
        "issues": issues,
        "issues_truncated": len(report.issues) > len(issues),
    }


def vortex_report_summary(report: Any) -> dict[str, Any]:
    games = [
        {
            "game_id": game.game_id,
            "profile_count": game.profile_count,
            "mod_count": game.mod_count,
            "snapshot_entries": game.snapshot_entries,
            "snapshot_base_paths": list(game.snapshot_base_paths),
        }
        for game in report.games
    ]
    return {
        "summary": f"Vortex {report.version}: {len(games)} managed game states found.",
        "version": report.version,
        "games": games,
    }


def system_snapshot_summary(snapshot: Any) -> dict[str, Any]:
    gib = float(1024**3)
    return {
        "summary": (
            f"{snapshot.os_name} {snapshot.os_release}; "
            f"{snapshot.cpu_logical} logical CPUs; "
            f"{snapshot.memory_available_bytes / gib:.1f} GiB RAM available."
        ),
        "os": f"{snapshot.os_name} {snapshot.os_release}",
        "machine": snapshot.machine,
        "cpu_logical": snapshot.cpu_logical,
        "memory_total_gib": round(snapshot.memory_total_bytes / gib, 1),
        "memory_available_gib": round(snapshot.memory_available_bytes / gib, 1),
        "disk_total_gib": round(snapshot.disk_total_bytes / gib, 1),
        "disk_free_gib": round(snapshot.disk_free_bytes / gib, 1),
        "gpu": dict(snapshot.gpu),
    }


def performance_command_summary(center: Any, text: str) -> dict[str, Any]:
    prompt = str(text).strip().casefold()
    if any(token in prompt for token in ("restore", "revert", "baseline")):
        result = center.restore()
        return {"summary": result.message, "mode": result.mode, "changed": result.changed}
    if "adaptive" in prompt:
        enabled = not any(token in prompt for token in ("disable", "off", "stop"))
        base = "ai" if any(token in prompt for token in (" ai ", "chatmpd")) else "balanced"
        status = center.set_adaptive(enabled, base_mode=base)
        return {"summary": f"Adaptive performance {'enabled' if enabled else 'disabled'}.", **status}
    if any(token in prompt for token in ("gaming", "game mode", "for games", "for gaming")):
        result = center.apply("gaming")
        return {"summary": result.message, "mode": result.mode, "changed": result.changed}
    if any(token in prompt for token in ("ai mode", "ai performance", "for ai", "chatmpd performance")):
        result = center.apply("ai")
        return {"summary": result.message, "mode": result.mode, "changed": result.changed}
    if "balanced" in prompt:
        result = center.apply("balanced")
        return {"summary": result.message, "mode": result.mode, "changed": result.changed}
    report = center.analyze()
    findings = [getattr(item, "summary", str(item)) for item in getattr(report, "findings", ())]
    summary = f"Performance analysis: {report.overall_score}/100 overall; bottleneck {report.bottleneck}."
    return {"summary": summary, "overall_score": report.overall_score,
            "gaming_score": report.gaming_score, "ai_score": report.ai_score,
            "balanced_score": report.balanced_score, "bottleneck": report.bottleneck,
            "findings": findings}


def default_model_registry() -> ModelRegistry:
    registry = ModelRegistry.discover(DEFAULT_MODEL_ROOTS)
    if not registry.models:
        raise RuntimeError("No compatible local GGUF models were found on Vader.")
    return registry


def _runtime_for_model(model: LocalModel) -> LlamaCppRuntime:
    return LlamaCppRuntime(
        RuntimeConfig(
            model_path=model.path,
            context_size=16_384,
            max_tokens=2_048,
        )
    )


class DefaultMediaSpecialist:
    """Own the managed ComfyUI image backend without exposing its workflow UI."""

    _REQUIRED_IMAGE_MODELS = (
        ("diffusion_models", "z_image_turbo_nvfp4.safetensors"),
        ("text_encoders", "qwen_3_4b_fp8_mixed.safetensors"),
        ("vae", "ae.safetensors"),
    )
    _REQUIRED_VIDEO_MODELS = (
        ("checkpoints", "ltxv-2b-0.9.8-distilled-fp8.safetensors"),
        ("text_encoders", "t5xxl_fp8_e4m3fn_scaled.safetensors"),
    )

    def __init__(
        self,
        runtime: MediaRuntime | None = None,
        *,
        assembler: FFmpegAssembler | None = None,
    ) -> None:
        self.runtime = runtime or MediaRuntime()
        self.assembler = assembler or FFmpegAssembler()

    def __call__(self, text: str) -> dict[str, Any]:
        plan = normalize_media_request(text)
        if plan.media_type == "video":
            return self._create_video(plan)
        missing = [
            str(self.runtime.config.models_dir / folder / name)
            for folder, name in self._REQUIRED_IMAGE_MODELS
            if not (self.runtime.config.models_dir / folder / name).is_file()
        ]
        if missing:
            raise RuntimeError("Image models are still being installed: " + "; ".join(missing))
        try:
            self.runtime.start()
            backend = ComfyUIBackend(
                ComfyUIClient(self.runtime.endpoint),
                workflow_builder=ZImageWorkflowBuilder().build,
                poll_interval=0.5,
                completion_timeout=1800,
            )
            result = MediaPipeline(backend).create(text)
        finally:
            self.runtime.stop()
        files = self._output_files(result.outputs)
        return {
            "summary": (
                f"Generated {len(files)} image output(s)."
                if files else "ComfyUI completed the image job."
            ),
            "status": result.status,
            "job_id": result.job_id,
            "files": files,
            "was_reframed": plan.was_reframed,
        }

    def _create_video(self, plan: Any) -> dict[str, Any]:
        missing = self._missing(self._REQUIRED_VIDEO_MODELS)
        if missing:
            raise RuntimeError("Video models are still being installed: " + "; ".join(missing))
        segments = plan_video_segments(plan)
        builder = LTXVideoWorkflowBuilder()
        files: list[str] = []
        job_ids: list[str] = []
        try:
            self.runtime.start()
            client = ComfyUIClient(self.runtime.endpoint)
            for segment in segments:
                backend = ComfyUIBackend(
                    client,
                    workflow_builder=lambda _unused, current=segment: builder.build_segment(plan, current),
                    poll_interval=0.5,
                    completion_timeout=3600,
                )
                result = backend.generate(plan)
                job_ids.append(result.job_id)
                files.extend(self._output_files(result.outputs))
        finally:
            self.runtime.stop()
        if not files:
            raise RuntimeError("ComfyUI completed the video job without a saved output.")
        assembled: str | None = None
        if len(files) > 1:
            destination = self.runtime.config.output_dir / "ChatMPD" / "ltx" / f"assembled_{uuid4().hex[:12]}.mp4"
            assembled = str(self.assembler.concat([Path(item) for item in files], destination))
        return {
            "summary": f"Generated {len(files)} video segment(s)" + (" and assembled the final video." if assembled else "."),
            "status": "completed",
            "job_ids": job_ids,
            "files": files,
            "assembled_file": assembled or files[0],
            "duration_seconds": plan.duration_seconds,
            "was_reframed": plan.was_reframed,
        }

    def _missing(self, required: tuple[tuple[str, str], ...]) -> list[str]:
        return [str(self.runtime.config.models_dir / folder / name)
                for folder, name in required
                if not (self.runtime.config.models_dir / folder / name).is_file()]

    def _output_files(self, outputs: Any) -> list[str]:
        files: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                filename = str(value.get("filename", "")).strip()
                if filename and value.get("type") == "output":
                    subfolder = str(value.get("subfolder", "")).strip()
                    path = str(self.runtime.config.output_dir / subfolder / filename)
                    if path not in files:
                        files.append(path)
                for child in value.values():
                    visit(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    visit(child)

        visit(outputs)
        return files


def build_default_orchestrator(*, start_automation_scheduler: bool = True) -> ChatMPDOrchestrator:
    registry = default_model_registry()
    services = build_platform_services(model_registry=registry)
    manager = ModelRuntimeManager(
        registry, runtime_factory=_runtime_for_model, selector=services.models.choose
    )
    assistant = DesktopAssistant(
        model_manager=manager,
        provider_factory=lambda endpoint: LlamaCppProvider(endpoint, timeout=300),
        context_provider=services.retrieval_context,
    )
    media = DefaultMediaSpecialist()
    services.performance.bind_runtime(assistant.release_runtime)

    def eso_handler(_text: str) -> dict[str, Any]:
        return eso_scan_summary(EsoAddonManager().scan())

    def vortex_handler(_text: str) -> dict[str, Any]:
        return vortex_report_summary(VortexInventory().scan())

    def system_handler(_text: str) -> dict[str, Any]:
        return system_snapshot_summary(SystemInspector().snapshot())

    def performance_handler(text: str) -> dict[str, Any]:
        return performance_command_summary(services.performance, text)

    orchestrator = ChatMPDOrchestrator(
        assistant=assistant,
        specialist_handlers={
            "eso": eso_handler,
            "vortex": vortex_handler,
            "system": system_handler,
            "performance": performance_handler,
            "media": media,
        },
        platform_services=services,
    )

    def automation_runner(command: str) -> str:
        try:
            result = orchestrator.command(command)
            services.activity.record("automation", result.message, details={"capability": result.capability})
            return result.message
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            services.activity.record("automation", "Automation run failed.", details={"error": message[:500]})
            return message

    if start_automation_scheduler:
        services.bind_automation_runner(automation_runner)
    return orchestrator
