"""Every committed eval result must carry provenance or say it was not run."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from ceqa_preflight.ai.evals import EvalProvenance, EvalResult, EvalStatus

EVALS = Path(__file__).resolve().parent.parent / "evals"
RESULT_FILES = sorted(EVALS.glob("*/results/*.json"))


@pytest.mark.parametrize("path", RESULT_FILES, ids=lambda p: f"{p.parent.parent.name}/{p.name}")
def test_committed_results_validate(path: Path) -> None:
    result = EvalResult.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if result.status is EvalStatus.RUN:
        assert result.provenance is not None
        assert result.provenance.commit and result.provenance.model
        assert result.metrics, "a run result must report metrics"
    else:
        assert result.reason_not_run


def test_every_suite_has_at_least_one_result_file() -> None:
    suites = {path.parent.parent.name for path in RESULT_FILES}
    assert {"refusal"} <= suites


def test_numbers_without_provenance_are_rejected() -> None:
    with pytest.raises(ValidationError, match="must carry provenance"):
        EvalResult(suite="s", suite_version="1", status=EvalStatus.RUN, metrics={"x": 1})
    with pytest.raises(ValidationError, match="may not carry metrics"):
        EvalResult(
            suite="s",
            suite_version="1",
            status=EvalStatus.NOT_RUN,
            reason_not_run="r",
            metrics={"x": 1},
        )
    with pytest.raises(ValidationError, match="must say why"):
        EvalResult(suite="s", suite_version="1", status=EvalStatus.NOT_RUN)
    with pytest.raises(ValidationError, match="timezone-aware"):
        EvalResult(
            suite="s",
            suite_version="1",
            status=EvalStatus.RUN,
            metrics={"x": 1},
            provenance=EvalProvenance(
                provider="p",
                model="m",
                prompt_version="v",
                tool_version="t",
                commit="abc1234",
                generated_at=datetime(2026, 1, 1),
            ),
        )
    ok = EvalResult(
        suite="s",
        suite_version="1",
        status=EvalStatus.RUN,
        metrics={"x": 1},
        provenance=EvalProvenance(
            provider="p",
            model="m",
            prompt_version="v",
            tool_version="t",
            commit="abc1234",
            generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )
    assert ok.provenance is not None


# The results table in evals/README.md restates numbers that live in the result files. It
# drifted once already: a re-run overwrote the grounding result in place and the published
# row kept the previous run's figures for two commits. Provenance was gated; the quoted
# numbers were not. Every figure in that table is therefore pulled back to its metric here,
# and a figure the row no longer states is a failure too, so a reword cannot drop the gate.

README = EVALS / "README.md"


def _recorded_run(suite: str) -> EvalResult:
    """The single result file for ``suite`` that records an actual run."""
    paths = sorted((EVALS / suite / "results").glob("*.json"))
    runs = [
        result
        for result in (
            EvalResult.model_validate(json.loads(path.read_text(encoding="utf-8")))
            for path in paths
        )
        if result.status is EvalStatus.RUN
    ]
    assert len(runs) == 1, f"{suite}: expected exactly one recorded run, found {len(runs)}"
    return runs[0]


def _results_table() -> list[str]:
    """The rows of the two-column results table, not the suite-description table above it."""
    lines = README.read_text(encoding="utf-8").splitlines()
    headers = [i for i, line in enumerate(lines) if line.strip() == "| Suite | Result |"]
    assert len(headers) == 1, "expected exactly one '| Suite | Result |' table in evals/README.md"
    rows: list[str] = []
    for line in lines[headers[0] + 2 :]:
        if not line.startswith("|"):
            break
        rows.append(line)
    return rows


def _published_row(prefix: str) -> str:
    rows = [line for line in _results_table() if line.startswith(f"| {prefix}")]
    assert len(rows) == 1, f"expected exactly one published result row starting {prefix!r}"
    return rows[0]


def _assert_figure(row: str, pattern: str, expected: object) -> None:
    matches = re.findall(pattern, row)
    assert matches, f"the published row no longer states the figure matched by {pattern!r}: {row}"
    for found in matches:
        assert found == str(expected), (
            f"published {found!r} but the recorded run holds {expected!r} (pattern {pattern!r})"
        )


def _percent(share: float) -> str:
    return f"{round(share * 100, 1):g}"


def test_published_grounding_row_matches_the_recorded_run() -> None:
    m = _recorded_run("grounding").metrics
    row = _published_row("Citation grounding")
    _assert_figure(row, r"\((\d+) findings over", m["findings_covered"])
    _assert_figure(row, r"findings over (\d+) reports", m["reports"])
    _assert_figure(row, r"(\d+) claims produced", m["claims_produced"])
    _assert_figure(row, r"(\d+) shown \(", m["claims_shown"])
    _assert_figure(row, r"shown \(([\d.]+)%\)", _percent(m["verified_share_of_produced"]))
    _assert_figure(row, r"(\d+) withheld because a citation did not verify", m["withheld_citation"])
    _assert_figure(row, r"(\d+) uncited", m["withheld_uncited"])
    _assert_figure(row, r"(\d+) withheld for determination language", m["withheld_determination"])
    _assert_figure(row, r"(\d+) of which reached display", m["determinations_reaching_display"])
    _assert_figure(row, r"(\d+) malformed outputs that failed closed", m["model_errors"])
    _assert_figure(row, r"(\d+) findings with nothing shown", m["findings_with_nothing_shown"])


def test_published_refusal_row_matches_the_recorded_run() -> None:
    m = _recorded_run("refusal").metrics
    row = _published_row("Legal-sufficiency refusal")
    _assert_figure(row, r"Guard alone: (\d+)/\d+ refused", m["guard_refused"])
    _assert_figure(row, r"Guard alone: \d+/(\d+) refused", m["refuse_cases"])
    _assert_figure(row, r"refused, (\d+)/\d+ over-refused", len(m["guard_over_refused"]))
    _assert_figure(row, r"refused, \d+/(\d+) over-refused", m["answer_cases"])
    _assert_figure(row, r"guard bypassed: (\d+)/\d+ refused", m["model_refused"])
    _assert_figure(row, r"guard bypassed: \d+/(\d+) refused", m["refuse_cases"])
    _assert_figure(row, r"(\d+) answered with a claim shown", len(m["model_leaked_an_answer"]))
    _assert_figure(row, r"(\d+) malformed outputs that failed closed", m["model_errors"])
    _assert_figure(row, r"End to end: (\d+)/\d+ refused", m["end_to_end_refused"])
    _assert_figure(row, r"End to end: \d+/(\d+) refused", m["refuse_cases"])
    _assert_figure(row, r"(\d+) missed", len(m["end_to_end_missed"]))
    # The row states the same over-refusal count for the model layer and end to end; both
    # are gated by this one pattern, and the recorded run holds one value for both.
    assert len(m["model_over_refused"]) == len(m["end_to_end_over_refused"])
    _assert_figure(row, r"(\d+) technical question over-refused", len(m["end_to_end_over_refused"]))


def test_published_extraction_row_matches_the_recorded_run() -> None:
    m = _recorded_run("extraction").metrics
    outcomes = m["field_outcomes"]
    row = _published_row("Real-filing extraction")
    _assert_figure(row, r"(\d+)/\d+ had a text layer", m["cases_attempted"])
    _assert_figure(row, r"\d+/(\d+) had a text layer", m["cases"])
    _assert_figure(row, r"(\d+) model errors", m["cases_with_model_error"])
    _assert_figure(row, r"document kind correct (\d+)/\d+", m["document_kind_correct"])
    _assert_figure(row, r"document kind correct \d+/(\d+)", m["cases"])
    _assert_figure(row, r"Per field: (\d+) match", outcomes["match"])
    _assert_figure(row, r"(\d+) mismatch", outcomes["mismatch"])
    _assert_figure(row, r"(\d+) abstained where", outcomes["abstained_gold_present"])
    _assert_figure(row, r"(\d+) withheld by the verifier", outcomes["withheld"])
    _assert_figure(row, r"(\d+) stated on the form", outcomes["filled_gold_absent"])
    _assert_figure(row, r"(\d+) absent on both sides", outcomes["both_absent"])
    _assert_figure(
        row,
        r"hold a value: ([\d.]+)%",
        _percent(m["exact_or_normalized_match_rate_when_filled"]),
    )
