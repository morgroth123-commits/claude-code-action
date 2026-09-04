from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from chatmpd.ltxvideo import (
    FFmpegAssembler,
    LTXVideoWorkflowBuilder,
    plan_video_segments,
)
from chatmpd.media import normalize_media_request


class LTXVideoTest(unittest.TestCase):
    def test_duration_is_split_into_native_four_second_segments(self) -> None:
        plan = normalize_media_request("make a 10 second cinematic video of a snowy forest")
        segments = plan_video_segments(plan)
        self.assertEqual([item.frames for item in segments], [97, 97, 49])
        self.assertEqual([item.index for item in segments], [0, 1, 2])
        self.assertEqual(sum(item.duration_seconds for item in segments), 10.0)

    def test_workflow_uses_native_ltx_nodes_and_h264_output(self) -> None:
        plan = normalize_media_request("make a 4 second video of a sunrise over mountains")
        segment = plan_video_segments(plan)[0]
        workflow = LTXVideoWorkflowBuilder().build_segment(plan, segment)
        types = {node["class_type"] for node in workflow.values()}
        for required in {"CheckpointLoaderSimple", "CLIPLoader", "EmptyLTXVLatentVideo",
                         "LTXVConditioning", "LTXVScheduler", "SamplerCustom",
                         "VAEDecode", "CreateVideo", "SaveVideo"}:
            self.assertIn(required, types)
        clip_loader = next(node for node in workflow.values() if node["class_type"] == "CLIPLoader")
        self.assertEqual(clip_loader["inputs"]["type"], "ltxv")
        latent = next(node for node in workflow.values() if node["class_type"] == "EmptyLTXVLatentVideo")
        self.assertEqual(latent["inputs"]["length"], 97)
        saver = next(node for node in workflow.values() if node["class_type"] == "SaveVideo")
        self.assertEqual(saver["inputs"]["format"], "mp4")
        self.assertEqual(saver["inputs"]["codec"], "h264")

    def test_ffmpeg_assembler_uses_concat_copy_then_validates_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / "a.mp4", root / "b.mp4"
            first.write_bytes(b"a")
            second.write_bytes(b"b")
            output = root / "joined.mp4"
            calls: list[list[str]] = []

            def runner(argv: list[str]) -> None:
                calls.append(list(argv))
                output.write_bytes(b"joined")

            assembler = FFmpegAssembler(executable="ffmpeg", runner=runner)
            result = assembler.concat([first, second], output)
            self.assertEqual(result, output)
            self.assertTrue(output.is_file())
            self.assertIn("-f", calls[0])
            self.assertIn("concat", calls[0])
            self.assertIn("copy", calls[0])


if __name__ == "__main__":
    unittest.main()
