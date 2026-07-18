"""Tests for controlled-label, aggregate-only pilot evidence processing."""

from pathlib import Path

import pytest

from ceqa_preflight.pilot import PilotDataError, summarize_pilot, write_pilot_templates


def _write_rows(path: Path, rows: list[str]) -> None:
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_summarize_pilot_returns_go_when_all_thresholds_are_met(tmp_path: Path) -> None:
    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(
        review_path,
        [
            "package_id,filing_type,rule_id,finding_status,disposition,severity,elapsed_seconds",
            "PKG_001,NOE,NOE-001,warning,true_positive,medium,120",
            "PKG_002,NOD,NOD-001,failure,true_positive,high,180",
        ],
    )
    _write_rows(
        baseline_path,
        [
            "package_id,filing_type,severity,was_missed",
            "PKG_001,NOE,high,false",
            "PKG_002,NOD,high,false",
        ],
    )

    summary = summarize_pilot(review_path, baseline_path)

    assert summary.go_no_go == "go"
    assert summary.actionable_precision == 1.0
    assert summary.high_severity_false_negative_rate == 0.0
    assert summary.median_report_seconds == 150.0


def test_summarize_pilot_returns_no_go_with_threshold_and_measurement_gaps(tmp_path: Path) -> None:
    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(
        review_path,
        [
            "package_id,filing_type,rule_id,finding_status,disposition,severity,elapsed_seconds",
            "PKG_001,NOE,NOE-001,warning,false_positive,high,300",
        ],
    )
    _write_rows(
        baseline_path,
        [
            "package_id,filing_type,severity,was_missed",
            "PKG_001,NOE,high,true",
        ],
    )

    summary = summarize_pilot(review_path, baseline_path)

    assert summary.go_no_go == "no_go"
    assert summary.actionable_precision == 0.0
    assert summary.high_severity_false_negative_rate == 1.0
    assert len(summary.reasons) == 3


def test_summarize_pilot_rejects_free_text_and_duplicate_reviews(tmp_path: Path) -> None:
    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(
        review_path,
        [
            "package_id,filing_type,rule_id,finding_status,disposition,severity,elapsed_seconds",
            "=FORMULA,NOE,NOE-001,warning,true_positive,medium,10",
        ],
    )
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    with pytest.raises(PilotDataError, match="spreadsheet formula"):
        summarize_pilot(review_path, baseline_path)


def test_pilot_templates_do_not_overwrite(tmp_path: Path) -> None:
    write_pilot_templates(tmp_path)

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_pilot_templates(tmp_path)
