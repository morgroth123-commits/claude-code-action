"""Plain-language capability routing for ChatMPD."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping


Handler = Callable[..., Any]


@dataclass(frozen=True)
class RouteDecision:
    capability: str
    requires_workspace: bool = False
    reason: str = ""


class RequestRouter:
    """Route one natural-language request to a ChatMPD capability."""

    def __init__(self, handlers: Mapping[str, Handler] | None = None) -> None:
        self.handlers = dict(handlers or {})

    def classify(self, text: str) -> RouteDecision:
        prompt = str(text).strip()
        if not prompt:
            raise ValueError("Describe what you want ChatMPD to do.")
        lowered = prompt.casefold()

        if any(token in lowered for token in (
            "elder scrolls online", " eso ", "eso addon", "minion",
            "harvestmap", "bugcatcher", "bandits ui", "lost treasure",
        )) or lowered.startswith("eso "):
            return RouteDecision("eso", False, "ESO specialist evidence is relevant.")

        if any(token in lowered for token in (
            "vortex", "load order", "deployment conflict", "mod profile",
            "mod deployment", "mod conflict",
        )):
            return RouteDecision("vortex", False, "Mod-management specialist is relevant.")

        if any(token in lowered for token in (
            "video", "image", "photo", "clip", "montage", "compilation",
            "cinematic", "upscale", "interpolate", "render",
        )) and any(token in lowered for token in (
            "create", "make", "generate", "edit", "assemble", "render", "upscale",
        )):
            return RouteDecision("media", False, "Media generation or editing is requested.")

        if any(token in lowered for token in (
            "project", "repository", "repo", "code", "source", "failing test",
            "failing tests", "unit test", "bugfix", "refactor",
        )):
            return RouteDecision("coding", True, "Project-aware coding tools are appropriate.")

        if any(token in lowered for token in (
            "performance", "bottleneck", "optimize my pc", "optimize this computer",
            "optimize this pc", "optimize vader", "speed up vader", "tune vader",
            "gaming mode", "ai mode", "performance mode",
            "fps stutter", "frame stutter",
        )):
            return RouteDecision("performance", False, "Performance analysis or optimization is requested.")

        if any(token in lowered for token in (
            "windows", "driver", "audio", "crackling", "process", "service",
            "startup", "install", "uninstall", "computer", "pc", "system",
            "disk space", "network", "bluetooth", "device manager",
        )):
            return RouteDecision("system", False, "Host inspection or configuration is requested.")

        return RouteDecision("chat", False, "No specialist capability is required.")

    def dispatch(self, text: str, **context: Any) -> Any:
        """Classify and invoke one configured capability handler."""

        decision = self.classify(text)
        handler = self.handlers.get(decision.capability)
        if handler is None:
            raise RuntimeError(
                f"ChatMPD capability is not configured: {decision.capability}"
            )
        if decision.requires_workspace and not context.get("workspace"):
            raise ValueError("This request needs a project folder.")
        return handler(text, **context)
