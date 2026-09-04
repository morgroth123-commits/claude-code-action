"""Core-only ComfyUI workflow builder for Z-Image-Turbo."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from .media import MediaPlan


@dataclass(frozen=True)
class ZImageWorkflowBuilder:
    seed: int | None = None
    width: int = 1024
    height: int = 1024
    filename_prefix: str = "ChatMPD"

    def __post_init__(self) -> None:
        if not 256 <= self.width <= 2048 or self.width % 16:
            raise ValueError("width must be a multiple of 16 between 256 and 2048")
        if not 256 <= self.height <= 2048 or self.height % 16:
            raise ValueError("height must be a multiple of 16 between 256 and 2048")

    def build(self, plan: MediaPlan) -> dict[str, dict[str, Any]]:
        seed = self.seed if self.seed is not None else secrets.randbits(63)
        return {
            "1": {"class_type": "UNETLoader", "inputs": {
                "unet_name": "z_image_turbo_nvfp4.safetensors", "weight_dtype": "default"}},
            "2": {"class_type": "CLIPLoader", "inputs": {
                "clip_name": "qwen_3_4b_fp8_mixed.safetensors",
                "type": "lumina2", "device": "default"}},
            "3": {"class_type": "VAELoader", "inputs": {
                "vae_name": "ae.safetensors"}},
            "11": {"class_type": "ModelSamplingAuraFlow", "inputs": {
                "model": ["1", 0], "shift": 3.0}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {
                "text": plan.prompt, "clip": ["2", 0]}},
            "5": {"class_type": "ConditioningZeroOut", "inputs": {
                "conditioning": ["4", 0]}},
            "6": {"class_type": "EmptySD3LatentImage", "inputs": {
                "width": self.width, "height": self.height, "batch_size": 1}},
            "7": {"class_type": "KSampler", "inputs": {
                "model": ["11", 0], "seed": int(seed), "steps": 8, "cfg": 1.0,
                "sampler_name": "res_multistep", "scheduler": "simple",
                "positive": ["4", 0], "negative": ["5", 0],
                "latent_image": ["6", 0], "denoise": 1.0}},
            "8": {"class_type": "VAEDecode", "inputs": {
                "samples": ["7", 0], "vae": ["3", 0]}},
            "9": {"class_type": "SaveImage", "inputs": {
                "images": ["8", 0], "filename_prefix": self.filename_prefix}},
        }
