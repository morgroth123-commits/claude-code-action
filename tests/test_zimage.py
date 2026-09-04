from __future__ import annotations

import unittest

from chatmpd.media import normalize_media_request
from chatmpd.zimage import ZImageWorkflowBuilder


class ZImageWorkflowTest(unittest.TestCase):
    def test_builds_native_core_workflow_for_vader_models(self) -> None:
        plan = normalize_media_request("Generate an image of a moonlit castle")
        workflow = ZImageWorkflowBuilder(seed=42).build(plan)

        self.assertEqual(workflow["1"]["class_type"], "UNETLoader")
        self.assertEqual(
            workflow["1"]["inputs"]["unet_name"],
            "z_image_turbo_nvfp4.safetensors",
        )
        self.assertEqual(workflow["2"]["inputs"]["clip_name"], "qwen_3_4b_fp8_mixed.safetensors")
        self.assertEqual(workflow["2"]["inputs"]["type"], "lumina2")
        self.assertEqual(workflow["3"]["inputs"]["vae_name"], "ae.safetensors")
        self.assertEqual(workflow["11"]["inputs"]["shift"], 3.0)
        self.assertEqual(workflow["7"]["inputs"]["steps"], 8)
        self.assertEqual(workflow["7"]["inputs"]["cfg"], 1.0)
        self.assertEqual(workflow["7"]["inputs"]["sampler_name"], "res_multistep")
        self.assertEqual(workflow["7"]["inputs"]["scheduler"], "simple")
        self.assertEqual(workflow["6"]["inputs"]["width"], 1024)
        self.assertEqual(workflow["6"]["inputs"]["height"], 1024)
        self.assertIn("moonlit castle", workflow["4"]["inputs"]["text"])
