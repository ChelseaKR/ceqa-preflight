"""What a comparison between two reports may and may not claim.

The interesting cases here are all the same shape: a delta the tool could compute by
guessing, which it declines to. Two findings that share a pairing key, a rule that did not
run in one report and is simply absent from the other, a later report produced against a
different ruleset — each is a place where an ordinary diff would report a clean result that
means nothing, and each is asserted here to come out labelled instead.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ceqa_preflight.cli import app
from ceqa_preflight.diffing import (
    DiffError,
    FindingChange,
    ProvenanceMismatch,
    SkipChange,
    diff_reports,
    exit_code_for,
    load_report,
)
from ceqa_preflight.models import (
    Confidence,
    FilingType,
    Finding,
    FindingStatus,
    InspectionReport,
    SkippedCheck,
    SkipReason,
)
from ceqa_preflight.reporting import render_diff_console, render_diff_html, render_diff_json

_runner = CliRunner()


def _finding(
    rule_id: str = "PDF-001",
    *,
    status: FindingStatus = FindingStatus.PASS,
    document: str | None = "notice.pdf",
    field: str | None = None,
    message: str = "The document has a text layer.",
    page: int | None = None,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        rule_version="1.0.0",
        status=status,
        title="Text layer present",
        message=message,
        document=document,
        field=field,
        page=page,
        remediation="No action needed.",
        confidence=Confidence.HIGH,
    )


def _skipped(rule_id: str, reason: SkipReason = SkipReason.NOT_SELECTED) -> SkippedCheck:
    return SkippedCheck(
        rule_id=rule_id,
        rule_version="1.0.0",
        title="Experimental filing rule",
        reason=reason,
        detail="It was not selected for this run.",
    )


def _report(
    findings: list[Finding] | None = None,
    *,
    manual_review: list[Finding] | None = None,
    not_run: list[SkippedCheck] | None = None,
    ruleset_version: str = "1.2.0",
    tool_version: str = "0.1.0",
    fingerprint: str = "a" * 64,
    filing_type: FilingType = FilingType.NOE,
) -> InspectionReport:
    return InspectionReport(
        tool_version=tool_version,
        ruleset_version=ruleset_version,
        generated_at=datetime(2026, 9, 1, tzinfo=UTC),
        input_fingerprint=fingerprint,
        filing_type=filing_type,
        findings=findings or [],
        manual_review=manual_review or [],
        not_run=not_run or [],
        disclaimer="Advisory only.",
    )


# --- what the comparison declines to guess --------------------------------------------


def test_two_findings_sharing_a_pairing_key_are_not_paired_by_list_order() -> None:
    """`rule_id` + `document` + `field` is the only identity the schema offers.

    Pairing two same-key findings positionally would report a "changed" that is an artifact
    of the order the engine happened to emit them in, and a reviewer would chase it.
    """
    before = _report([_finding(page=2), _finding(page=7)])
    after = _report([_finding(page=7), _finding(page=2)])

    delta = diff_reports(before, after).findings[0]

    assert delta.change is FindingChange.NOT_COMPARABLE
    assert (delta.before_count, delta.after_count) == (2, 2)
    assert delta.changed_attributes == []


def test_a_rule_that_did_not_run_and_is_absent_later_is_not_resolved() -> None:
    """The later report says nothing about it. That is not the finding clearing."""
    before = _report(not_run=[_skipped("NOE-M001")])
    after = _report()

    delta = diff_reports(before, after).not_run[0]

    assert delta.change is SkipChange.NOT_COMPARABLE
    rendered = render_diff_console(diff_reports(before, after))
    assert "cannot be compared" in rendered


def test_a_rule_that_did_not_run_and_produced_a_finding_later_is_reported_as_having_run() -> None:
    before = _report(not_run=[_skipped("NOE-001")])
    after = _report([_finding("NOE-001", status=FindingStatus.WARNING)])

    diff = diff_reports(before, after)

    assert diff.not_run[0].change is SkipChange.NOW_RAN
    assert diff.findings[0].change is FindingChange.ADDED


def test_a_rule_that_ran_and_did_not_run_later_is_reported_as_no_longer_run() -> None:
    before = _report([_finding("NOE-001", status=FindingStatus.WARNING)])
    after = _report(not_run=[_skipped("NOE-001")])

    diff = diff_reports(before, after)

    assert diff.not_run[0].change is SkipChange.NOW_NOT_RUN
    assert diff.findings[0].change is FindingChange.REMOVED
    assert diff.findings[0].regression is False


def test_a_changed_skip_reason_is_reported_rather_than_treated_as_unchanged() -> None:
    before = _report(not_run=[_skipped("NOE-M001", SkipReason.NOT_SELECTED)])
    after = _report(not_run=[_skipped("NOE-M001", SkipReason.WITHDRAWN)])

    delta = diff_reports(before, after).not_run[0]

    assert delta.change is SkipChange.REASON_CHANGED
    assert (delta.before_reason, delta.after_reason) == (
        SkipReason.NOT_SELECTED,
        SkipReason.WITHDRAWN,
    )


# --- provenance is stated, never merged away ------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"ruleset_version": "9.9.9"}, ProvenanceMismatch.RULESET_VERSION),
        ({"tool_version": "9.9.9"}, ProvenanceMismatch.TOOL_VERSION),
        ({"fingerprint": "b" * 64}, ProvenanceMismatch.INPUT_FINGERPRINT),
        ({"filing_type": FilingType.NOD}, ProvenanceMismatch.FILING_TYPE),
    ],
)
def test_every_provenance_difference_is_named_before_any_delta(
    kwargs: dict[str, object], expected: ProvenanceMismatch
) -> None:
    diff = diff_reports(_report(), _report(**kwargs))  # type: ignore[arg-type]

    assert expected in diff.mismatches
    assert "Before any comparison" in render_diff_console(diff)


def test_a_report_schema_the_tool_does_not_know_is_refused_not_compared() -> None:
    """`InspectionReport` does not validate this field, so nothing else would catch it."""
    payload = json.loads(_report().model_dump_json())
    payload["report_schema_version"] = "2.0"

    with pytest.raises(DiffError, match=re.escape("2.0")):
        load_report(json.dumps(payload))


def test_a_report_the_model_rejects_is_refused_with_the_reason() -> None:
    with pytest.raises(DiffError, match="not a check report"):
        load_report("not json at all")


# --- what counts as a regression ------------------------------------------------------


def test_a_new_failure_is_a_regression_and_exits_one() -> None:
    diff = diff_reports(_report(), _report([_finding("PDF-006", status=FindingStatus.FAILURE)]))

    assert diff.regressions and exit_code_for(diff) == 1


def test_a_finding_that_became_a_failure_is_a_regression() -> None:
    before = _report([_finding(status=FindingStatus.WARNING)])
    after = _report([_finding(status=FindingStatus.FAILURE)])

    diff = diff_reports(before, after)

    assert diff.findings[0].change is FindingChange.CHANGED
    assert diff.findings[0].changed_attributes == ["status"]
    assert diff.findings[0].regression and exit_code_for(diff) == 1


def test_a_failure_that_cleared_is_a_change_but_not_a_regression() -> None:
    before = _report([_finding(status=FindingStatus.FAILURE)])
    after = _report([_finding(status=FindingStatus.PASS)])

    diff = diff_reports(before, after)

    assert diff.findings[0].change is FindingChange.CHANGED
    assert not diff.regressions and exit_code_for(diff) == 0


def test_a_failure_that_stayed_a_failure_is_not_counted_as_new() -> None:
    diff = diff_reports(
        _report([_finding(status=FindingStatus.FAILURE)]),
        _report([_finding(status=FindingStatus.FAILURE)]),
    )

    assert not diff.regressions
    assert diff.findings[0].change is FindingChange.UNCHANGED


def test_a_manual_review_item_that_became_a_failure_is_one_delta_not_two() -> None:
    """Manual-review items live in their own list but carry the same identity."""
    before = _report(manual_review=[_finding(status=FindingStatus.MANUAL)])
    after = _report([_finding(status=FindingStatus.FAILURE)])

    diff = diff_reports(before, after)

    assert len(diff.findings) == 1
    assert diff.findings[0].change is FindingChange.CHANGED
    assert diff.findings[0].regression


# --- rendering ------------------------------------------------------------------------


def test_an_unchanged_comparison_says_so_and_names_the_fingerprint() -> None:
    report = _report([_finding()])

    rendered = render_diff_console(diff_reports(report, report))

    assert "No finding and no skipped check moved" in rendered
    assert "a" * 64 in rendered


def test_an_unchanged_comparison_is_not_claimed_when_a_skip_moved() -> None:
    """An empty findings delta beside a moved `not_run` entry is not "no change"."""
    before = _report(not_run=[_skipped("NOE-M001", SkipReason.NOT_SELECTED)])
    after = _report(not_run=[_skipped("NOE-M001", SkipReason.WITHDRAWN)])

    diff = diff_reports(before, after)

    assert not diff.is_unchanged
    assert "No finding and no skipped check moved" not in render_diff_console(diff)


def test_the_json_comparison_carries_only_stable_identifiers_for_every_delta() -> None:
    diff = diff_reports(_report(), _report([_finding(status=FindingStatus.FAILURE)]))

    payload = json.loads(render_diff_json(diff))

    assert payload["diff_schema_version"] == "1.0"
    assert payload["findings"][0]["change"] == "added"
    assert payload["findings"][0]["after"]["status"] == "failure"
    assert payload["findings"][0]["regression"] is True


def test_the_html_comparison_is_self_contained_and_scriptless() -> None:
    diff = diff_reports(_report(), _report([_finding(status=FindingStatus.FAILURE)]))

    rendered = render_diff_html(diff)

    assert rendered.startswith("<!doctype html>")
    assert "<script" not in rendered
    assert "PDF-001" in rendered


# --- the command ----------------------------------------------------------------------


def _write(path: Path, report: InspectionReport) -> Path:
    path.write_text(report.model_dump_json(), encoding="utf-8")
    return path


def test_the_command_exits_one_on_a_regression_and_zero_otherwise(tmp_path: Path) -> None:
    before = _write(tmp_path / "before.json", _report())
    after = _write(tmp_path / "after.json", _report([_finding(status=FindingStatus.FAILURE)]))

    assert _runner.invoke(app, ["diff", str(before), str(after)]).exit_code == 1
    assert _runner.invoke(app, ["diff", str(after), str(before)]).exit_code == 0


def test_the_command_exits_two_on_an_unreadable_report(tmp_path: Path) -> None:
    good = _write(tmp_path / "good.json", _report())
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")

    result = _runner.invoke(app, ["diff", str(good), str(bad)])

    assert result.exit_code == 2
    assert "Input error" in result.output


def test_the_command_writes_the_requested_format_to_a_file(tmp_path: Path) -> None:
    before = _write(tmp_path / "before.json", _report())
    after = _write(tmp_path / "after.json", _report([_finding()]))
    destination = tmp_path / "comparison.html"

    result = _runner.invoke(
        app, ["diff", str(before), str(after), "--format", "html", "--output", str(destination)]
    )

    assert result.exit_code == 0
    assert destination.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_an_unknown_format_is_a_usage_error(tmp_path: Path) -> None:
    report = _write(tmp_path / "report.json", _report())

    result = _runner.invoke(app, ["diff", str(report), str(report), "--format", "yaml"])

    assert result.exit_code == 2


def test_the_comparison_prose_follows_the_locale_but_the_json_does_not(tmp_path: Path) -> None:
    before = _write(tmp_path / "before.json", _report())
    after = _write(tmp_path / "after.json", _report([_finding(status=FindingStatus.FAILURE)]))

    english = _runner.invoke(app, ["diff", str(before), str(after)])
    spanish = _runner.invoke(app, ["--locale", "es", "diff", str(before), str(after)])
    # Written to a file rather than read off stdout: a Spanish run prints the
    # unreviewed-translation notice above its output, which is prose about the run and not
    # part of the machine-readable document.
    destination = tmp_path / "es.json"
    _runner.invoke(
        app,
        [
            "--locale",
            "es",
            "diff",
            str(before),
            str(after),
            "--format",
            "json",
            "--output",
            str(destination),
        ],
    )

    assert english.output != spanish.output
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["findings"][0]["change"] == "added"
    assert payload["findings"][0]["after"]["status"] == "failure"


@pytest.mark.parametrize(
    ("before_report", "after_report", "expected"),
    [
        (
            _report([_finding(page=2), _finding(page=7)]),
            _report([_finding(page=7), _finding(page=2)]),
            "no pairing between them is knowable",
        ),
        (
            _report(),
            _report([_finding(status=FindingStatus.FAILURE, message="No text layer.")]),
            "[NEW] PDF-001 (notice.pdf): failure: No text layer.",
        ),
        (
            _report([_finding(status=FindingStatus.WARNING, message="No text layer.")]),
            _report(),
            "[GONE] PDF-001 (notice.pdf): was warning: No text layer.",
        ),
        (
            _report([_finding(status=FindingStatus.WARNING)]),
            _report([_finding(status=FindingStatus.FAILURE, page=3)]),
            "[CHANGED] PDF-001 (notice.pdf): warning -> failure (status, page)",
        ),
    ],
    ids=["not-comparable", "added", "removed", "changed"],
)
def test_every_console_change_line_says_which_way_the_finding_moved(
    before_report: InspectionReport, after_report: InspectionReport, expected: str
) -> None:
    """Each branch renders the direction, not just the fact that something differs."""
    assert expected in render_diff_console(diff_reports(before_report, after_report))


def test_an_existing_directory_is_written_into_not_beside(tmp_path: Path) -> None:
    """`check --output` takes a directory, so `diff --output` is reached for the same way.

    Before this, a directory argument fell through the extension branch and produced a
    sibling file — `reports.txt` next to `reports/` — which the success line then named as
    though the person had asked for it.
    """
    before = _write(tmp_path / "before.json", _report())
    after = _write(tmp_path / "after.json", _report([_finding()]))
    destination = tmp_path / "reports"
    destination.mkdir()

    result = _runner.invoke(app, ["diff", str(before), str(after), "--output", str(destination)])

    assert result.exit_code == 0
    assert (destination / "comparison.txt").exists()
    assert not (tmp_path / "reports.txt").exists()


def test_an_extensionless_file_path_still_gains_the_format_suffix(tmp_path: Path) -> None:
    before = _write(tmp_path / "before.json", _report())
    after = _write(tmp_path / "after.json", _report([_finding()]))

    result = _runner.invoke(
        app,
        ["diff", str(before), str(after), "--format", "json", "--output", str(tmp_path / "out")],
    )

    assert result.exit_code == 0
    assert (tmp_path / "out.json").exists()
