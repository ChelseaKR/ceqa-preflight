"""Deterministic execution of declarative CEQA Preflight rules."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from enum import StrEnum
from typing import Any

from pydantic import Field

from ceqa_preflight.models import (
    Confidence,
    Evidence,
    FilingType,
    Finding,
    FindingStatus,
    StrictModel,
)
from ceqa_preflight.rule_catalog import RuleCatalog, RuleDefinition, RuleLifecycle


class RuleOutcomeStatus(StrEnum):
    """Check-local outcomes before conservative report-status mapping."""

    # This is a report outcome, not a credential.
    PASS = "pass"  # nosec B105
    WARNING = "warning"
    FAILURE = "failure"
    INDETERMINATE = "indeterminate"


class RuleContext(StrictModel):
    """Typed non-secret facts supplied to rule functions."""

    filing_type: FilingType
    facts: dict[str, Any] = Field(default_factory=dict)


class RuleOutcome(StrictModel):
    """A check result that is transformed into a stable report finding."""

    status: RuleOutcomeStatus
    message: str = Field(min_length=1)
    document: str | None = None
    page: int | None = Field(default=None, ge=1)
    field: str | None = None
    evidence: Evidence = Field(default_factory=Evidence)
    remediation: str = Field(min_length=1)
    confidence: Confidence = Confidence.HIGH


class RuleRun(StrictModel):
    """Results and process status for a complete deterministic rule run."""

    findings: list[Finding] = Field(default_factory=list)
    exit_code: int = Field(ge=0, le=2)


RuleCheck = Callable[[RuleContext, RuleDefinition], Iterable[RuleOutcome]]


class RuleEngine:
    """Runs only allow-listed rule functions in source order of the catalog."""

    def __init__(self, catalog: RuleCatalog, registry: Mapping[str, RuleCheck]) -> None:
        self._catalog = catalog
        self._registry = dict(registry)
        unknown = sorted({rule.check for rule in catalog.rules if rule.check not in self._registry})
        if unknown:
            raise ValueError(f"catalog references unknown check names: {', '.join(unknown)}")

    def run(self, context: RuleContext, *, include_experimental: bool = False) -> RuleRun:
        """Run applicable rules in catalog order, isolating individual check failures."""

        findings: list[Finding] = []
        exit_code = 0
        for rule in self._catalog.rules:
            if not _is_enabled(rule, context.filing_type, include_experimental):
                continue
            try:
                outcomes = self._registry[rule.check](context, rule)
                findings.extend(_finding_from_outcome(rule, outcome) for outcome in outcomes)
            except Exception:
                findings.append(_internal_error_finding(rule))
                exit_code = 2
        return RuleRun(findings=findings, exit_code=exit_code)


def _is_enabled(rule: RuleDefinition, filing_type: FilingType, include_experimental: bool) -> bool:
    if filing_type not in rule.filing_types:
        return False
    if rule.lifecycle is RuleLifecycle.ACTIVE:
        return True
    return rule.lifecycle is RuleLifecycle.EXPERIMENTAL and include_experimental


def _finding_from_outcome(rule: RuleDefinition, outcome: RuleOutcome) -> Finding:
    status = (
        FindingStatus.MANUAL
        if outcome.status is RuleOutcomeStatus.INDETERMINATE
        else FindingStatus(outcome.status.value)
    )
    return Finding(
        rule_id=rule.id,
        rule_version=rule.version,
        status=status,
        title=rule.title,
        message=outcome.message,
        document=outcome.document,
        page=outcome.page,
        field=outcome.field,
        evidence=outcome.evidence,
        remediation=outcome.remediation,
        source=rule.source,
        confidence=outcome.confidence,
    )


def _internal_error_finding(rule: RuleDefinition) -> Finding:
    return Finding(
        rule_id=rule.id,
        rule_version=rule.version,
        status=FindingStatus.WARNING,
        title=f"{rule.title}: internal rule error",
        message="This check could not complete. No package conclusion was made.",
        remediation="Review this item manually and report the rule identifier if it recurs.",
        source=rule.source,
        confidence=Confidence.LOW,
    )
