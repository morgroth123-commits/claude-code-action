from __future__ import annotations

import unittest

from chatmpd.media import MediaPipeline, normalize_media_request


class _RecordingBackend:
    def __init__(self) -> None:
        self.plans = []

    def generate(self, plan):
        self.plans.append(plan)
        return {"status": "queued", "job_id": "media-1"}


class MediaPipelineTest(unittest.TestCase):
    def test_plain_language_video_request_infers_safe_fictional_adult_defaults(self) -> None:
        plan = normalize_media_request(
            "Create a 20 minute realistic erotic compilation with an amateur video look"
        )
        self.assertEqual(plan.media_type, "video")
        self.assertEqual(plan.duration_seconds, 1200)
        self.assertTrue(plan.fictional_adults)
        self.assertTrue(plan.consent_required)
        self.assertFalse(plan.identifiable_real_people)

    def test_explicit_request_is_reframed_without_losing_format_or_duration(self) -> None:
        plan = normalize_media_request(
            "Create a 20 minute deepthroat compilation in photorealistic amateur style"
        )
        self.assertTrue(plan.was_reframed)
        self.assertEqual(plan.duration_seconds, 1200)
        self.assertEqual(plan.structure, "compilation")
        self.assertNotIn("deepthroat", plan.prompt.casefold())
        self.assertIn("sensual", plan.prompt.casefold())

    def test_pipeline_hides_backend_complexity_from_plain_language_command(self) -> None:
        backend = _RecordingBackend()
        pipeline = MediaPipeline(backend)
        result = pipeline.create(
            "Create a 30 second realistic fictional adult sensual video"
        )
        self.assertEqual(result["status"], "queued")
        self.assertEqual(len(backend.plans), 1)
        self.assertEqual(backend.plans[0].duration_seconds, 30)


if __name__ == "__main__":
    unittest.main()
