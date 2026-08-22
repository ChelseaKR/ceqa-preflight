"""Every committed eval result must carry provenance or say it was not run."""

from __future__ import annotations

import json
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
