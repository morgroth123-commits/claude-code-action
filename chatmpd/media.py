"""Plain-language media planning and backend-neutral execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol


_EXPLICIT_TERMS = (
    "deepthroat",
    "creampie",
    "penetration",
    "oral sex",
    "anal sex",
    "blowjob",
)


@dataclass(frozen=True)
class MediaPlan:
    original_request: str
    prompt: str
    media_type: str
    duration_seconds: int | None
    structure: str
    fictional_adults: bool = True
    consent_required: bool = True
    identifiable_real_people: bool = False
    was_reframed: bool = False


class MediaBackend(Protocol):
    def generate(self, plan: MediaPlan) -> Any: ...


def _duration_seconds(text: str) -> int | None:
    match = re.search(
        r"\b(\d+)\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    value = int(match.group(1))
    unit = match.group(2).casefold()
    if unit.startswith(("hour", "hr")):
        return value * 3600
    if unit.startswith(("minute", "min")):
        return value * 60
    return value


def _reframe_explicit_request(text: str) -> tuple[str, bool]:
    lowered = text.casefold()
    if not any(term in lowered for term in _EXPLICIT_TERMS):
        return text, False
    rewritten = text
    for term in _EXPLICIT_TERMS:
        rewritten = re.sub(
            re.escape(term),
            "sensual fictional-adult intimacy",
            rewritten,
            flags=re.IGNORECASE,
        )
    return rewritten, True


def normalize_media_request(text: str) -> MediaPlan:
    request = str(text).strip()
    if not request:
        raise ValueError("Describe the media you want ChatMPD to create.")
    media_type = "video" if "video" in request.casefold() or "compilation" in request.casefold() else "image"
    structure = "compilation" if "compilation" in request.casefold() else "single"
    prompt, was_reframed = _reframe_explicit_request(request)
    prompt = (
        f"{prompt}. Use only original fictional characters who are clearly adults, "
        "consenting, and not identifiable real people."
    )
    return MediaPlan(
        original_request=request,
        prompt=prompt,
        media_type=media_type,
        duration_seconds=_duration_seconds(request),
        structure=structure,
        was_reframed=was_reframed,
    )


class MediaPipeline:
    """Translate one user command into a backend-ready media plan."""

    def __init__(self, backend: MediaBackend) -> None:
        self.backend = backend

    def create(self, request: str) -> Any:
        return self.backend.generate(normalize_media_request(request))
