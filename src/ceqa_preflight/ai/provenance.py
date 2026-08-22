"""Provenance stamps for anything a model produced.

Every AI output and every recorded eval result names the provider, the model, the prompt
version, the tool version, and the time. Eval results additionally require the commit,
so a number can always be traced to the exact code and prompt that produced it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field

from ceqa_preflight import __version__
from ceqa_preflight.ai.client import ModelClient
from ceqa_preflight.models import StrictModel

AI_GENERATED_LABEL = (
    "AI-generated draft. Advisory only; not a finding, not legal advice, and not a "
    "determination of CEQA compliance or legal sufficiency. Review every value."
)


class Provenance(StrictModel):
    """Where a model output came from."""

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    generated_at: datetime
    commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{7,40}$")


def provenance_for(
    client: ModelClient, prompt_version: str, *, commit: str | None = None
) -> Provenance:
    return Provenance(
        provider=client.provider,
        model=client.model,
        prompt_version=prompt_version,
        tool_version=__version__,
        generated_at=datetime.now(UTC),
        commit=commit,
    )
