"""Deterministic execution of declarative CEQA Preflight rules."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from enum import StrEnum
from typing import Any

from pydantic import Field

from ceqa_preflight.i18n import gettext as _
from ceqa_preflight.models import (
    Confidence,
    Evidence,
    FilingType,
    Finding,
    FindingStatus,
    SkippedCheck,
    SkipReason,
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
    not_run: list[SkippedCheck] = Field(default_factory=list)
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
        not_run: list[SkippedCheck] = []
        exit_code = 0
        for rule in self._catalog.rules:
            if context.filing_type not in rule.filing_types:
                # Not applicable to this filing type, so it is not a check that was skipped.
                continue
            reason = _lifecycle_skip_reason(rule, include_experimental)
            if reason is not None:
                not_run.append(skipped_check(rule, reason))
                continue
            try:
                outcomes = self._registry[rule.check](context, rule)
                findings.extend(_finding_from_outcome(rule, outcome) for outcome in outcomes)
            except Exception:
                findings.append(_internal_error_finding(rule))
                exit_code = 2
        return RuleRun(findings=findings, not_run=not_run, exit_code=exit_code)


def _lifecycle_skip_reason(rule: RuleDefinition, include_experimental: bool) -> SkipReason | None:
    """Return why a filing-type-applicable rule did not run, or ``None`` when it ran."""

    if rule.lifecycle is RuleLifecycle.ACTIVE:
        return None
    if rule.lifecycle is RuleLifecycle.EXPERIMENTAL:
        return None if include_experimental else SkipReason.EXPERIMENTAL_NOT_INCLUDED
    return SkipReason.WITHDRAWN


def _skip_detail(reason: SkipReason) -> str:
    """Say why one applicable check did not run, in the active locale.

    Built per call rather than held in a module constant so the sentence follows the
    locale the run was given; a dictionary evaluated at import time would freeze whichever
    language happened to be active when the module was first loaded.
    """

    details = {
        SkipReason.EXPERIMENTAL_NOT_INCLUDED: _(
            "This check is experimental and runs only with --include-experimental. It did not "
            "run, so this report makes no statement about what it covers."
        ),
        SkipReason.WITHDRAWN: _(
            "This check has been withdrawn from the active rule set and did not run, so this "
            "report makes no statement about what it covers."
        ),
        SkipReason.NOT_SELECTED: _(
            "This check did not run because --rules limited the run to other rule identifiers, "
            "so this report makes no statement about what it covers. Re-run without --rules to "
            "include it."
        ),
        SkipReason.EXCLUDED_BY_REQUEST: _(
            "This check did not run because --exclude-rules named it, so this report makes no "
            "statement about what it covers. Re-run without that exclusion to include it."
        ),
    }
    return details[reason]


def skipped_check(rule: RuleDefinition, reason: SkipReason) -> SkippedCheck:
    """Record one applicable rule that did not run, with its source and the way to run it."""

    return SkippedCheck(
        rule_id=rule.id,
        rule_version=rule.version,
        title=rule.title,
        reason=reason,
        detail=_skip_detail(reason),
        source=rule.source,
    )


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
        title=_("{title}: internal rule error").format(title=rule.title),
        message=_("This check could not complete. No package conclusion was made."),
        remediation=_("Review this item manually and report the rule identifier if it recurs."),
        source=rule.source,
        confidence=Confidence.LOW,
    )
