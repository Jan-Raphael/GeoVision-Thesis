"""Tests for `ai.evaluation.report` — every writer produces the files it promises.

Content correctness is the upstream modules' job (`test_evaluation_metrics.py`
etc.); what matters here is that the reproducibility manifest is complete and
that each writer's output actually lands on disk in the shape `run_all.py`
and the thesis LaTeX/Markdown will expect to find it in.
"""

from __future__ import annotations

import json

from ai.evaluation.benchmark import BenchmarkResult, hardware_info
from ai.evaluation.detector_eval import AgreementReport, DetectionAP, MAPReport
from ai.evaluation.metrics import LabeledPrediction, summarize_classification
from ai.evaluation.progress_eval import evaluate_against_ground_truth
from ai.evaluation.report import (
    BackboneComparisonRow,
    new_run_id,
    run_output_dir,
    write_agreement_report,
    write_backbone_comparison,
    write_benchmark_table,
    write_classification_report,
    write_manifest,
    write_map_report,
    write_progress_evaluation,
)
from ai.progress.mapping import MacroStage


class TestRunIdAndOutputDir:
    def test_run_id_is_sortable_and_unique_enough(self) -> None:
        a = new_run_id()
        b = new_run_id()
        assert a <= b  # timestamps, so never decreasing across a fast call pair

    def test_output_dir_is_created(self, tmp_path) -> None:
        directory = run_output_dir("abc", root=tmp_path)
        assert directory.is_dir()
        assert directory == tmp_path / "abc"


class TestManifest:
    def test_records_hardware_seed_and_package_versions(self, tmp_path) -> None:
        directory = run_output_dir("run1", root=tmp_path)
        manifest = write_manifest(directory, hardware=hardware_info(), seed=42, notes="test run")
        payload = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))

        assert manifest.seed == 42
        assert payload["seed"] == 42
        assert payload["notes"] == "test run"
        assert "python" in payload["package_versions"]
        assert payload["hardware"]["python_version"]


class TestClassificationReportWriter:
    def test_writes_tables_and_figures(self, tmp_path) -> None:
        predictions = [
            LabeledPrediction(0, 0, 0.9, (0.9, 0.05, 0.05)),
            LabeledPrediction(1, 1, 0.8, (0.1, 0.8, 0.1)),
            LabeledPrediction(2, 1, 0.6, (0.1, 0.6, 0.3)),
        ]
        report = summarize_classification(predictions, ("A", "B", "C"))
        out = write_classification_report(tmp_path, report)

        assert (out / "summary.json").exists()
        assert (out / "per_class_metrics.csv").exists()
        assert (out / "confusion_matrix.png").exists()
        assert (out / "reliability_diagram.png").exists()
        assert (out / "calibration.json").exists()


class TestBackboneComparisonWriter:
    def test_writes_the_table_and_a_scatter_even_with_one_row(self, tmp_path) -> None:
        rows = [
            BackboneComparisonRow(
                model="stub-classifier",
                top1_accuracy=None,
                macro_f1=None,
                params=None,
                size_mb=None,
                cpu_ms=12.3,
                gpu_ms=None,
            )
        ]
        out = write_backbone_comparison(tmp_path, rows)
        assert (out / "comparison.csv").exists()
        assert (out / "accuracy_vs_latency.png").exists()

    def test_handles_zero_plottable_rows_without_raising(self, tmp_path) -> None:
        rows = [
            BackboneComparisonRow(
                model="incomplete",
                top1_accuracy=None,
                macro_f1=None,
                params=None,
                size_mb=None,
                cpu_ms=None,
                gpu_ms=None,
            )
        ]
        out = write_backbone_comparison(tmp_path, rows)
        assert (out / "accuracy_vs_latency.png").exists()


class TestBenchmarkTableWriter:
    def test_writes_one_row_per_result(self, tmp_path) -> None:
        result = BenchmarkResult(
            model_name="stub",
            architecture="stub",
            is_stub=True,
            device="cpu",
            n_images=5,
            n_warmup=2,
            mean_ms=1.0,
            median_ms=1.0,
            p95_ms=1.0,
            min_ms=0.9,
            max_ms=1.1,
            throughput_ips=1000.0,
        )
        out = write_benchmark_table(tmp_path, [result, result])
        rows = (out / "latency.csv").read_text(encoding="utf-8").strip().splitlines()
        assert len(rows) == 3  # header + 2 rows


class TestDetectorWriters:
    def test_map_report_writes_summary_and_per_class_table(self, tmp_path) -> None:
        report = MAPReport(
            per_class_ap50=(DetectionAP("column", 0.5, 0.8, 10),),
            map50=0.8,
            map50_95=0.6,
        )
        out = write_map_report(tmp_path, report)
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        assert summary["map50"] == 0.8

    def test_agreement_report_writes_confusion_rows(self, tmp_path) -> None:
        report = AgreementReport(
            n_comparable=1,
            n_total=1,
            agreement_rate=1.0,
            confusion={stage: dict.fromkeys(MacroStage, 0) for stage in MacroStage},
        )
        out = write_agreement_report(tmp_path, report)
        assert (out / "agreement.json").exists()
        assert (out / "agreement_confusion.csv").exists()


class TestProgressEvaluationWriter:
    def test_writes_series_csv_and_the_raw_vs_smoothed_figure(self, tmp_path) -> None:
        from ai.evaluation.run_all import _worked_example_series

        results, ground_truth = _worked_example_series()
        evaluation = evaluate_against_ground_truth(results, ground_truth)
        out = write_progress_evaluation(tmp_path, evaluation, results)

        assert (out / "summary.json").exists()
        assert (out / "series.csv").exists()
        assert (out / "raw_vs_smoothed.png").exists()

        series_rows = (out / "series.csv").read_text(encoding="utf-8").strip().splitlines()
        assert len(series_rows) == 1 + len(results)  # header + one row per window
