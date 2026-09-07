"""Tests for controlled-label, aggregate-only pilot evidence processing."""

from pathlib import Path

import pytest

from ceqa_preflight.pilot import (
    REVIEW_HEADERS,
    PilotDataError,
    summarize_pilot,
    write_pilot_templates,
)

_HEADER = ",".join(REVIEW_HEADERS)


def _write_rows(path: Path, rows: list[str]) -> None:
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_summarize_pilot_returns_go_when_all_thresholds_are_met(tmp_path: Path) -> None:
    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(
        review_path,
        [
            _HEADER,
            "PKG_001,NOE,NOE-001,warning,true_positive,medium,120,REVIEWER_1,,",
            "PKG_002,NOD,NOD-001,failure,true_positive,high,180,REVIEWER_1,,",
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
            _HEADER,
            "PKG_001,NOE,NOE-001,warning,false_positive,high,300,REVIEWER_1,,",
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
            _HEADER,
            "=FORMULA,NOE,NOE-001,warning,true_positive,medium,10,REVIEWER_1,,",
        ],
    )
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    with pytest.raises(PilotDataError, match="spreadsheet formula"):
        summarize_pilot(review_path, baseline_path)


def test_pilot_templates_do_not_overwrite(tmp_path: Path) -> None:
    write_pilot_templates(tmp_path)

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_pilot_templates(tmp_path)


def _pair_rows(agreeing: int, disagreeing: int) -> list[str]:
    """Two reviewers over the same findings: `agreeing` shared labels, `disagreeing` split.

    Both reviewers see every finding, so the pair is comparable on all of them. The
    disagreements are the second reviewer's alone, which is what makes the marginals
    differ and kappa worth computing.
    """

    rows: list[str] = []
    for index in range(agreeing + disagreeing):
        package = f"PKG_{index:03d}"
        disposition = "true_positive"
        other = "true_positive" if index < agreeing else "false_positive"
        rows.append(f"{package},NOE,NOE-001,warning,{disposition},medium,60,REVIEWER_1,,")
        rows.append(f"{package},NOE,NOE-001,warning,{other},medium,60,REVIEWER_2,,")
    return rows


def test_two_reviewers_disagreeing_on_one_of_ten_findings_report_the_hand_computed_kappa(
    tmp_path: Path,
) -> None:
    """Reviewer 1 labels ten true positives; reviewer 2 labels nine and one false positive.

        observed = 9/10
        expected = (10/10)(9/10) + (0/10)(1/10) = 9/10
        kappa    = (9/10 - 9/10) / (1 - 9/10)   = 0

    Marginals of 10/0 against 9/1 make almost all of that 90% agreement the agreement
    chance already predicts, so kappa is zero. This is exactly why the raw percentage is
    not published on its own: it reads as near-consensus and it is not.
    """

    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(review_path, [_HEADER, *_pair_rows(agreeing=9, disagreeing=1)])
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    summary = summarize_pilot(review_path, baseline_path)

    assert len(summary.reviewer_agreement) == 1
    pair = summary.reviewer_agreement[0]
    assert (pair.rule_id, pair.reviewer_a, pair.reviewer_b) == (
        "NOE-001",
        "REVIEWER_1",
        "REVIEWER_2",
    )
    assert pair.compared_findings == 10
    assert pair.agreed_findings == 9
    assert pair.percent_agreement == 0.9
    # expected = (10/10)(9/10) + (0/10)(1/10) = 0.9; kappa = (0.9 - 0.9) / (1 - 0.9) = 0.
    assert pair.cohens_kappa == 0.0
    assert pair.kappa_undefined is False


def test_a_reviewer_pair_that_never_labelled_the_same_finding_produces_no_agreement_row(
    tmp_path: Path,
) -> None:
    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(
        review_path,
        [
            _HEADER,
            "PKG_001,NOE,NOE-001,warning,true_positive,medium,60,REVIEWER_1,,",
            "PKG_002,NOE,NOE-001,warning,true_positive,medium,60,REVIEWER_2,,",
        ],
    )
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    summary = summarize_pilot(review_path, baseline_path)

    assert summary.reviewer_agreement == []
    assert summary.rules[0].independent_reviewers == 2


def test_identical_labels_throughout_leave_kappa_undefined_rather_than_perfect(
    tmp_path: Path,
) -> None:
    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(review_path, [_HEADER, *_pair_rows(agreeing=3, disagreeing=0)])
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    summary = summarize_pilot(review_path, baseline_path)

    pair = summary.reviewer_agreement[0]
    assert pair.percent_agreement == 1.0
    assert pair.cohens_kappa is None
    assert pair.kappa_undefined is True


def test_a_rule_with_two_of_two_approvals_reports_an_interval_not_a_bare_hundred_percent(
    tmp_path: Path,
) -> None:
    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(
        review_path,
        [
            _HEADER,
            "PKG_001,NOE,NOE-001,warning,true_positive,medium,60,REVIEWER_1,,",
            "PKG_001,NOE,NOE-001,warning,true_positive,medium,60,REVIEWER_2,,",
        ],
    )
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    summary = summarize_pilot(review_path, baseline_path)

    rule = summary.rules[0]
    assert rule.precision == 1.0
    assert rule.precision_interval_low is not None
    assert rule.precision_interval_low < 0.35, "two of two must not read as certainty"
    assert rule.precision_interval_high == 1.0
    assert rule.independent_reviewers == 2
    assert rule.meets_reviewer_coverage is True
    assert summary.reviewer_coverage_threshold == 2
    assert summary.interval_confidence_level == 0.95


def test_a_rule_with_no_true_or_false_positive_labels_is_not_measurable_rather_than_zero(
    tmp_path: Path,
) -> None:
    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(
        review_path,
        [
            _HEADER,
            "PKG_001,NOE,NOE-001,warning,indeterminate,medium,60,REVIEWER_1,,",
            "PKG_001,NOE,NOE-002,warning,not_actionable,medium,60,REVIEWER_1,,",
        ],
    )
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    summary = summarize_pilot(review_path, baseline_path)

    assert [rule.rule_id for rule in summary.rules] == ["NOE-001", "NOE-002"]
    for rule in summary.rules:
        assert rule.labelled_findings == 0
        assert rule.precision is None
        assert rule.precision_interval_low is None
        assert rule.precision_interval_high is None
        assert rule.meets_reviewer_coverage is False
    assert summary.actionable_precision is None


def test_a_reviewer_who_dismisses_a_seeded_defect_is_recorded_as_a_miss(tmp_path: Path) -> None:
    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(
        review_path,
        [
            _HEADER,
            "SYN_001,NOE,PDF-003,warning,true_positive,medium,30,REVIEWER_1,SYNTH_A,scanned",
            "SYN_002,NOE,PDF-003,warning,false_positive,medium,30,REVIEWER_1,SYNTH_A,scanned",
            "SYN_003,NOE,PDF-003,warning,true_positive,medium,30,REVIEWER_2,SYNTH_A,scanned",
        ],
    )
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    summary = summarize_pilot(review_path, baseline_path)

    assert summary.calibration_findings == 3
    first, second = summary.calibration
    assert (first.reviewer_id, first.expected_defect) == ("REVIEWER_1", "scanned")
    assert (first.seeded_findings, first.identified, first.missed) == (2, 1, 1)
    assert (second.reviewer_id, second.identified, second.missed) == ("REVIEWER_2", 1, 0)


def test_calibration_rows_never_enter_the_precision_timing_or_go_no_go_figures(
    tmp_path: Path,
) -> None:
    """A synthetic package contains the defect its rule looks for, by construction.

    Counting it would raise the precision that the pilot exists to measure on real
    filings, so the aggregate here must be identical to the one from the real row alone.
    """

    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(
        review_path,
        [
            _HEADER,
            "PKG_001,NOE,NOE-001,warning,false_positive,medium,60,REVIEWER_1,,",
            "SYN_001,NOE,PDF-003,warning,true_positive,medium,30,REVIEWER_1,SYNTH_A,scanned",
            "SYN_002,NOE,PDF-003,warning,true_positive,medium,30,REVIEWER_1,SYNTH_A,scanned",
        ],
    )
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    summary = summarize_pilot(review_path, baseline_path)

    assert summary.reviewed_findings == 1
    assert summary.reviewed_packages == 1
    assert summary.true_positives == 0
    assert summary.actionable_precision == 0.0
    assert summary.median_report_seconds == 60.0
    assert [rule.rule_id for rule in summary.rules] == ["NOE-001"]
    assert summary.go_no_go == "no_go"


def test_a_half_filled_calibration_row_is_refused(tmp_path: Path) -> None:
    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(
        review_path,
        [
            _HEADER,
            "SYN_001,NOE,PDF-003,warning,true_positive,medium,30,REVIEWER_1,,scanned",
        ],
    )
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    with pytest.raises(PilotDataError, match="must be given together or both left empty"):
        summarize_pilot(review_path, baseline_path)


def test_an_unknown_seeded_defect_is_refused_rather_than_carried_as_free_text(
    tmp_path: Path,
) -> None:
    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(
        review_path,
        [
            _HEADER,
            "SYN_001,NOE,PDF-003,warning,true_positive,medium,30,REVIEWER_1,SYNTH_A,badly-scanned",
        ],
    )
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    with pytest.raises(PilotDataError, match="expected_defect"):
        summarize_pilot(review_path, baseline_path)


def test_one_package_id_cannot_be_both_synthetic_and_a_real_filing(tmp_path: Path) -> None:
    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(
        review_path,
        [
            _HEADER,
            "PKG_001,NOE,NOE-001,warning,true_positive,medium,60,REVIEWER_1,,",
            "PKG_001,NOE,PDF-003,warning,true_positive,medium,60,REVIEWER_1,SYNTH_A,scanned",
        ],
    )
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    with pytest.raises(PilotDataError, match="either synthetic or a real filing"):
        summarize_pilot(review_path, baseline_path)


def test_two_reviewers_of_one_finding_are_two_rows_not_a_duplicate(tmp_path: Path) -> None:
    review_path, baseline_path = write_pilot_templates(tmp_path)
    _write_rows(
        review_path,
        [
            _HEADER,
            "PKG_001,NOE,NOE-001,warning,true_positive,medium,60,REVIEWER_1,,",
            "PKG_001,NOE,NOE-001,warning,true_positive,medium,60,REVIEWER_1,,",
        ],
    )
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    with pytest.raises(PilotDataError, match="duplicate package_id, rule_id, finding_status"):
        summarize_pilot(review_path, baseline_path)


def test_a_template_from_the_earlier_version_is_named_as_such(tmp_path: Path) -> None:
    review_path = tmp_path / "finding-review.csv"
    baseline_path = tmp_path / "manual-baseline.csv"
    _write_rows(
        review_path,
        [
            "package_id,filing_type,rule_id,finding_status,disposition,severity,elapsed_seconds",
            "PKG_001,NOE,NOE-001,warning,true_positive,medium,60",
        ],
    )
    _write_rows(baseline_path, ["package_id,filing_type,severity,was_missed"])

    with pytest.raises(PilotDataError, match="this file uses the earlier template"):
        summarize_pilot(review_path, baseline_path)


def test_the_new_template_carries_the_reviewer_and_calibration_columns(tmp_path: Path) -> None:
    review_path, _ = write_pilot_templates(tmp_path)

    header = review_path.read_text(encoding="utf-8").splitlines()[0]

    assert header.endswith("elapsed_seconds,reviewer_id,synth_seed,expected_defect")
