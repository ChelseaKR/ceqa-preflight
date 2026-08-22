"""The contract for committed eval results.

Every result file under ``evals/*/results/`` validates against ``EvalResult``. A result that
was actually run names its provider, model, prompt version, tool version, commit, and time;
a result that was not run says ``not_run`` and carries no numbers. A test enforces this, so
a number can never be committed without the run that produced it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from ceqa_preflight.models import StrictModel


class EvalStatus(StrEnum):
    RUN = "run"
    NOT_RUN = "not_run"


class EvalProvenance(StrictModel):
    """Provenance for a recorded run; unlike CLI provenance, the commit is required."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    commit: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    generated_at: datetime
    notes: str | None = None


class EvalResult(StrictModel):
    suite: str = Field(min_length=1)
    suite_version: str = Field(min_length=1)
    status: EvalStatus
    provenance: EvalProvenance | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    cases: list[dict[str, Any]] = Field(default_factory=list)
    reason_not_run: str | None = None

    @model_validator(mode="after")
    def require_provenance_for_numbers(self) -> EvalResult:
        if self.status is EvalStatus.RUN:
            if self.provenance is None:
                raise ValueError("a run result must carry provenance")
            if self.provenance.generated_at.tzinfo is None:
                raise ValueError("provenance time must be timezone-aware")
        elif self.metrics or self.cases:
            raise ValueError("a not_run result may not carry metrics or cases")
        elif not self.reason_not_run:
            raise ValueError("a not_run result must say why")
        return self
