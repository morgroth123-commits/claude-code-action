"""Hardware-aware native ComfyUI LTX-Video workflows and clip assembly."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .media import MediaPlan


@dataclass(frozen=True)
class VideoSegment:
    index: int
    duration_seconds: float
    frames: int
    seed: int


def _seed(prompt: str, index: int) -> int:
    digest = hashlib.sha256(f"{prompt}|ltx|{index}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF


def plan_video_segments(
    plan: MediaPlan, *, fps: int = 24, max_frames: int = 97, max_seconds: int = 1200
) -> tuple[VideoSegment, ...]:
    if fps < 1 or max_frames < 9 or (max_frames - 1) % 8:
        raise ValueError("Invalid LTX video geometry.")
    total = float(plan.duration_seconds or ((max_frames - 1) / fps))
    if total <= 0 or total > max_seconds:
        raise ValueError(f"Video duration must be between 1 and {max_seconds} seconds.")
    native_seconds = (max_frames - 1) / fps
    segments: list[VideoSegment] = []
    remaining = total
    index = 0
    while remaining > 1e-9:
        requested = min(native_seconds, remaining)
        temporal_steps = max(1, int((requested * fps + 7.999999) // 8))
        frames = min(max_frames, temporal_steps * 8 + 1)
        segments.append(VideoSegment(index, requested, frames, _seed(plan.prompt, index)))
        remaining -= requested
        index += 1
    return tuple(segments)


class LTXVideoWorkflowBuilder:
    """Build native ComfyUI LTX 2B text-to-video jobs for a 12 GB GPU."""

    def __init__(
        self,
        *,
        checkpoint: str = "ltxv-2b-0.9.8-distilled-fp8.safetensors",
        text_encoder: str = "t5xxl_fp8_e4m3fn_scaled.safetensors",
        width: int = 768,
        height: int = 512,
        fps: int = 24,
    ) -> None:
        if width % 32 or height % 32 or fps < 1:
            raise ValueError("LTX dimensions must be multiples of 32 and fps must be positive.")
        self.checkpoint = checkpoint
        self.text_encoder = text_encoder
        self.width = width
        self.height = height
        self.fps = fps

    def build_segment(self, plan: MediaPlan, segment: VideoSegment) -> dict[str, Any]:
        negative = (
            "low quality, worst quality, deformed, distorted, disfigured, "
            "motion smear, motion artifacts, bad anatomy"
        )
        prefix = f"ChatMPD/ltx/segment_{segment.index:03d}"
        return {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": self.checkpoint}},
            "2": {"class_type": "CLIPLoader", "inputs": {
                "clip_name": self.text_encoder, "type": "ltxv", "device": "cpu"}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": plan.prompt, "clip": ["2", 0]}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["2", 0]}},
            "5": {"class_type": "EmptyLTXVLatentVideo", "inputs": {
                "width": self.width, "height": self.height, "length": segment.frames, "batch_size": 1}},
            "6": {"class_type": "LTXVConditioning", "inputs": {
                "positive": ["3", 0], "negative": ["4", 0], "frame_rate": 25.0}},
            "7": {"class_type": "LTXVScheduler", "inputs": {
                "steps": 30, "max_shift": 2.05, "base_shift": 0.95,
                "stretch": True, "terminal": 0.1, "latent": ["5", 0]}},
            "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
            "9": {"class_type": "SamplerCustom", "inputs": {
                "model": ["1", 0], "add_noise": True, "noise_seed": segment.seed,
                "cfg": 3.0, "positive": ["6", 0], "negative": ["6", 1],
                "sampler": ["8", 0], "sigmas": ["7", 0], "latent_image": ["5", 0]}},
            "10": {"class_type": "VAEDecode", "inputs": {
                "samples": ["9", 0], "vae": ["1", 2]}},
            "11": {"class_type": "CreateVideo", "inputs": {
                "images": ["10", 0], "fps": float(self.fps),
                "bit_depth": 8, "color_space": "sRGB"}},
            "12": {"class_type": "SaveVideo", "inputs": {
                "video": ["11", 0], "filename_prefix": prefix,
                "format": "mp4", "codec": "h264"}},
        }


Runner = Callable[[list[str]], None]


class FFmpegAssembler:
    def __init__(self, *, executable: str = "ffmpeg", runner: Runner | None = None) -> None:
        self.executable = executable
        self._runner = runner or self._run
    def concat(self, clips: list[Path], output: Path) -> Path:
        sources = [Path(item).resolve() for item in clips]
        if not sources or any(not item.is_file() for item in sources):
            raise ValueError("Every video segment must exist before assembly.")
        destination = Path(output).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".txt", dir=destination.parent, delete=False
        ) as stream:
            for source in sources:
                escaped = source.as_posix().replace("'", "'\\''")
                stream.write(f"file '{escaped}'\n")
            listing = Path(stream.name)
        try:
            destination.unlink(missing_ok=True)
            self._runner([
                self.executable, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(listing),
                "-c", "copy", str(destination),
            ])
        finally:
            listing.unlink(missing_ok=True)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise RuntimeError("FFmpeg did not create the assembled video.")
        return destination

    @staticmethod
    def _run(argv: list[str]) -> None:
        executable = shutil.which(argv[0]) or argv[0]
        argv = [executable, *argv[1:]]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, creationflags=flags, timeout=300,
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip()[-1000:]
            raise RuntimeError(f"FFmpeg assembly failed: {detail}")
