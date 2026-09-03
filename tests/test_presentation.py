from pathlib import Path
from types import SimpleNamespace
import unittest

from chatmpd.presentation import (
    PALETTES,
    CheckPresentation,
    TaskPresentation,
    contrast_ratio,
    format_task_presentation,
    palette_for,
    present_error,
    present_task_outcome,
    step_text_scale,
    task_byte_usage,
)


class ResultPresentationTest(unittest.TestCase):
    def test_success_preserves_summary_files_checks_and_state_path(self) -> None:
        outcome = SimpleNamespace(
            result=SimpleNamespace(
                status="succeeded",
                summary="Repaired the calculator.",
                changed_files=["calculator.py"],
                checks=[SimpleNamespace(argv=["python", "-m", "unittest"], exit_code=0)],
                state_file=Path("C:/project/.chatmpd/runs/1/run.json"),
            )
        )

        result = present_task_outcome(outcome)

        self.assertEqual(result.kind, "success")
        self.assertEqual(result.summary, "Repaired the calculator.")
        self.assertEqual(result.changed_files, ("calculator.py",))
        self.assertEqual(result.checks, (CheckPresentation("python -m unittest", True),))
        self.assertEqual(result.state_file, Path("C:/project/.chatmpd/runs/1/run.json"))

    def test_failed_check_uses_verification_failure_kind(self) -> None:
        outcome = SimpleNamespace(
            result=SimpleNamespace(
                status="failed",
                summary="The repair did not pass.",
                changed_files=[],
                checks=[SimpleNamespace(argv=["python", "-m", "unittest"], exit_code=1)],
                state_file=Path("C:/project/.chatmpd/runs/2/run.json"),
            )
        )

        result = present_task_outcome(outcome)

        self.assertEqual(result.kind, "verification_failed")
        self.assertFalse(result.checks[0].passed)
        self.assertIn("FAILED: python -m unittest", format_task_presentation(result))

    def test_error_detail_is_flattened_bounded_and_retryable(self) -> None:
        result = present_error("local model\nnot ready")
        self.assertEqual(result.kind, "error")
        self.assertEqual(result.summary, "local model not ready")
        self.assertIn("fix the problem and try again", format_task_presentation(result).lower())

    def test_task_usage_counts_utf8_bytes(self) -> None:
        self.assertEqual(task_byte_usage("Aé"), (3, 32_768))


class AppearancePresentationTest(unittest.TestCase):
    def test_custom_palettes_meet_text_contrast_target(self) -> None:
        for name in ("light", "dark"):
            palette = palette_for(name)
            self.assertGreaterEqual(contrast_ratio(palette.text, palette.canvas), 4.5)
            self.assertGreaterEqual(
                contrast_ratio(palette.muted_text, palette.surface), 4.5
            )

    def test_every_palette_contains_semantic_non_color_labels(self) -> None:
        self.assertEqual(set(PALETTES), {"system", "light", "dark"})
        for palette in PALETTES.values():
            self.assertTrue(palette.status_labels["success"])
            self.assertTrue(palette.status_labels["warning"])
            self.assertTrue(palette.status_labels["error"])

    def test_text_scale_steps_are_bounded(self) -> None:
        self.assertEqual(step_text_scale(100, 1), 110)
        self.assertEqual(step_text_scale(100, -1), 90)
        self.assertEqual(step_text_scale(160, 1), 160)
        self.assertEqual(step_text_scale(90, -1), 90)
