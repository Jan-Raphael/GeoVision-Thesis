"""Tests for `ai.evaluation.run_all` — the `gv-evaluate` CLI.

Two things matter most here: that the worked example this script demonstrates
with actually reproduces the vault's hand-verified numbers (a standing check
that this module's understanding of the aggregator is correct), and that the
whole command runs end to end, today, with nothing but the stub models —
which is the entire point of building Module 15 before Module 07/08 unblock.
"""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from ai.evaluation.run_all import (
    _load_labeled_directory,
    _resolve_classifier,
    _resolve_detector,
    _worked_example_series,
    main,
)
from ai.models.stub import StubClassifier, StubDetector

# The exact `displayed_pct` sequence from Progress-Calculation.md §8's worked
# example — Project NG_00, two cameras, six days, ratchet holding on day 6.
_VAULT_WORKED_EXAMPLE = (28.0, 29.3, 30.7, 31.7, 33.5, 33.5)


class TestWorkedExampleSeries:
    def test_reproduces_the_vault_documented_displayed_series(self) -> None:
        results, _ = _worked_example_series()
        displayed = [round(window.displayed_pct, 1) for window in results]
        assert displayed == list(_VAULT_WORKED_EXAMPLE)

    def test_day_six_demonstrates_the_ratchet_holding(self) -> None:
        """Vault: 'Day 6 shows the design working ... the ratchet held'."""
        results, _ = _worked_example_series()
        day5, day6 = results[4], results[5]
        assert day6.raw_pct < day5.raw_pct  # the occluded camera pulled the raw value down
        assert day6.displayed_pct == day5.displayed_pct  # but the ratchet held it steady
        assert day6.regressed is False  # not yet a sanctioned release — only one down window

    def test_ground_truth_points_align_with_the_series_by_day(self) -> None:
        results, ground_truth = _worked_example_series()
        assert len(results) == len(ground_truth)
        for window, point in zip(results, ground_truth, strict=True):
            assert window.window_start.date() == point.day


class TestResolveClassifier:
    def test_no_checkpoint_returns_the_stub(self) -> None:
        model, note = _resolve_classifier(None)
        assert isinstance(model, StubClassifier)
        assert "stub" in note

    def test_a_missing_checkpoint_path_raises_rather_than_silently_falling_back(
        self, tmp_path
    ) -> None:
        missing = tmp_path / "does-not-exist.pt"
        with pytest.raises(FileNotFoundError):
            _resolve_classifier(missing)

    def test_an_existing_checkpoint_still_falls_back_with_a_clear_note(self, tmp_path) -> None:
        """Module 07's loader does not exist yet — the fallback must say so, not pretend."""
        checkpoint = tmp_path / "best.pt"
        checkpoint.write_bytes(b"not a real checkpoint")
        model, note = _resolve_classifier(checkpoint)
        assert isinstance(model, StubClassifier)
        assert "Module 07" in note


class TestResolveDetector:
    def test_no_checkpoint_returns_the_stub(self) -> None:
        model, note = _resolve_detector(None)
        assert isinstance(model, StubDetector)
        assert "stub" in note

    def test_a_missing_checkpoint_path_raises(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            _resolve_detector(tmp_path / "missing.pt")


class TestMainEndToEnd:
    def test_runs_with_no_arguments_and_writes_a_complete_run_directory(self, tmp_path) -> None:
        exit_code = main(
            ["--out-root", str(tmp_path), "--run-id", "test-run", "--n-benchmark-images", "3"]
        )
        assert exit_code == 0

        run_dir = tmp_path / "test-run"
        assert (run_dir / "manifest.json").exists()
        assert (run_dir / "index.json").exists()
        assert (run_dir / "benchmarks" / "latency.csv").exists()
        assert (run_dir / "progress" / "summary.json").exists()
        assert (run_dir / "progress" / "raw_vs_smoothed.png").exists()

    def test_index_lists_what_it_could_not_produce_and_why(self, tmp_path) -> None:
        main(["--out-root", str(tmp_path), "--run-id", "gap-check", "--n-benchmark-images", "2"])
        index = json.loads((tmp_path / "gap-check" / "index.json").read_text(encoding="utf-8"))

        assert any("classifier metrics" in item for item in index["skipped"])
        assert any("mAP" in item for item in index["skipped"])
        assert any("progress evaluation" in item for item in index["completed"])

    def test_a_nonexistent_classifier_checkpoint_fails_loudly(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            main(
                [
                    "--out-root",
                    str(tmp_path),
                    "--classifier",
                    str(tmp_path / "nope.pt"),
                ]
            )


def _write_test_split(root) -> None:
    """A tiny two-class labelled split, laid out the way `dataset/processed/test/` will be."""
    rng = np.random.default_rng(9)
    for class_dir, count in (("site_clearing", 2), ("columns", 2)):
        target = root / class_dir
        target.mkdir(parents=True)
        for index in range(count):
            image = rng.integers(60, 200, size=(64, 64, 3), dtype=np.uint8)
            ok, buffer = cv2.imencode(".jpg", image)
            assert ok
            (target / f"img{index}.jpg").write_bytes(bytes(buffer))


class TestLoadLabeledDirectory:
    def test_reads_every_image_under_every_known_class_folder(self, tmp_path) -> None:
        _write_test_split(tmp_path)
        rows = _load_labeled_directory(tmp_path, StubClassifier())
        assert len(rows) == 4  # 2 classes x 2 images

    def test_true_index_matches_the_folder_not_the_prediction(self, tmp_path) -> None:
        _write_test_split(tmp_path)
        rows = _load_labeled_directory(tmp_path, StubClassifier())
        # `site_clearing` -> class index 0, `columns` -> class index 4
        # (Construction-Stages.md); both must appear as *true* indices
        # regardless of what the stub happened to predict.
        true_indices = {row[0] for row in rows}
        assert true_indices == {0, 4}

    def test_an_unrecognised_folder_name_is_skipped_not_an_error(self, tmp_path) -> None:
        (tmp_path / "not_a_real_stage").mkdir()
        rows = _load_labeled_directory(tmp_path, StubClassifier())
        assert rows == []

    def test_main_produces_real_classifier_metrics_given_a_test_split(self, tmp_path) -> None:
        split_dir = tmp_path / "split"
        _write_test_split(split_dir)
        main(
            [
                "--out-root",
                str(tmp_path / "out"),
                "--run-id",
                "with-split",
                "--test-images",
                str(split_dir),
                "--n-benchmark-images",
                "2",
            ]
        )
        run_dir = tmp_path / "out" / "with-split"
        assert (run_dir / "classifier" / "summary.json").exists()
        assert (run_dir / "classifier" / "confusion_matrix.png").exists()

        index = json.loads((run_dir / "index.json").read_text(encoding="utf-8"))
        assert any("classifier metrics (n=4" in item for item in index["completed"])
