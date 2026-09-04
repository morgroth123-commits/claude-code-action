"""Managed screenshots and local-only vision routing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


CaptureBackend = Callable[[Path], None]
VisionProvider = Callable[[Path, str], Any]


def _default_capture(path: Path) -> None:
    try:
        from PIL import ImageGrab
    except ImportError as error:
        raise RuntimeError("Screen capture requires the local Pillow package.") from error
    image = ImageGrab.grab(all_screens=True)
    try:
        image.save(path, format="PNG")
    finally:
        image.close()


class LocalVision:
    def __init__(
        self,
        root: Path,
        *,
        provider: VisionProvider | None = None,
        capture_backend: CaptureBackend | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.provider = provider
        self.capture_backend = capture_backend or _default_capture
        self.root.mkdir(parents=True, exist_ok=True)

    def capture_screen(self) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        target = self.root / f"screenshot-{stamp}-{uuid4().hex[:8]}.png"
        self.capture_backend(target)
        if not target.is_file() or target.stat().st_size <= 0:
            raise RuntimeError("Screen capture backend did not create a usable image.")
        return target

    def health(self) -> dict[str, Any]:
        return {
            "ready": self.provider is not None,
            "mode": "local-only",
            "provider": "configured" if self.provider is not None else "not configured",
            "screenshots": "available",
        }

    def analyze(self, image_path: Path, prompt: str) -> Any:
        if self.provider is None:
            raise RuntimeError("No local vision model is configured; ChatMPD will not fall back to a cloud vision service.")
        image = Path(image_path).expanduser().resolve()
        if not image.is_file():
            raise FileNotFoundError(image)
        question = str(prompt).strip()
        if not question:
            raise ValueError("Vision prompt cannot be blank.")
        return self.provider(image, question)
