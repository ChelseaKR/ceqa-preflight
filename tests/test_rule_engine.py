"""Tests for deterministic, isolated rule execution."""

from __future__ import annotations

import pytest

from ceqa_preflight.models import FilingType, FindingStatus, SkipReason, SourceCitation
from ceqa_preflight.rule_catalog import RuleCatalog, RuleDefinition, RuleLifecycle
from ceqa_preflight.rule_engine import (
    RuleContext,
    RuleEngine,
    RuleOutcome,
    RuleOutcomeStatus,
)


def _definition(
    rule_id: str,
    check: str,
    *,
    lifecycle: RuleLifecycle = RuleLifecycle.ACTIVE,
    filing_types: list[FilingType] | None = None,
) -> RuleDefinition:
    return RuleDefinition(
        id=rule_id,
        version="1.0.0",
        title=f"{rule_id} title",
        check=check,
        lifecycle=lifecycle,
        filing_types=filing_types or [FilingType.NOD, FilingType.NOE],
        source=SourceCitation(title="Official guidance", url="https://lci.ca.gov/sch/faq/"),
    )


def _outcome(status: RuleOutcomeStatus = RuleOutcomeStatus.PASS) -> RuleOutcome:
    return RuleOutcome(status=status, message="Test result", remediation="Review the test result.")


def test_runs_in_catalog_order_and_maps_indeterminate_to_manual() -> None:
    catalog = RuleCatalog(
        catalog_version="1.0.0",
        rules=[_definition("CORE-001", "first"), _definition("CORE-002", "second")],
    )
    engine = RuleEngine(
        catalog,
        {
            "first": lambda *_: [_outcome()],
            "second": lambda *_: [_outcome(RuleOutcomeStatus.INDETERMINATE)],
        },
    )

    result = engine.run(RuleContext(filing_type=FilingType.NOD))

    assert [finding.rule_id for finding in result.findings] == ["CORE-001", "CORE-002"]
    assert result.findings[1].status is FindingStatus.MANUAL
    assert result.exit_code == 0


def test_filters_lifecycle_and_filing_type() -> None:
    catalog = RuleCatalog(
        catalog_version="1.0.0",
        rules=[
            _definition("CORE-001", "active"),
            _definition("CORE-002", "experimental", lifecycle=RuleLifecycle.EXPERIMENTAL),
            _definition("CORE-003", "retired", lifecycle=RuleLifecycle.RETIRED),
            _definition("NOD-001", "nod", filing_types=[FilingType.NOD]),
        ],
    )
    registry = {
        name: lambda *_: [_outcome()] for name in ["active", "experimental", "retired", "nod"]
    }
    engine = RuleEngine(catalog, registry)

    default = engine.run(RuleContext(filing_type=FilingType.NOE))
    experimental = engine.run(RuleContext(filing_type=FilingType.NOE), include_experimental=True)

    assert [finding.rule_id for finding in default.findings] == ["CORE-001"]
    assert [finding.rule_id for finding in experimental.findings] == ["CORE-001", "CORE-002"]
    # A rule that applied but did not run is recorded; NOD-001 does not apply to an NOE
    # filing at all, so it is not reported as a skipped check.
    assert [(skipped.rule_id, skipped.reason) for skipped in default.not_run] == [
        ("CORE-002", SkipReason.EXPERIMENTAL_NOT_INCLUDED),
        ("CORE-003", SkipReason.WITHDRAWN),
    ]
    assert [skipped.rule_id for skipped in experimental.not_run] == ["CORE-003"]
    assert all(skipped.detail and skipped.source for skipped in default.not_run)


def test_unknown_and_failing_checks_are_safe() -> None:
    unknown_catalog = RuleCatalog(
        catalog_version="1.0.0", rules=[_definition("CORE-001", "missing")]
    )
    with pytest.raises(ValueError, match="unknown check"):
        RuleEngine(unknown_catalog, {})

    catalog = RuleCatalog(catalog_version="1.0.0", rules=[_definition("CORE-002", "broken")])
    engine = RuleEngine(catalog, {"broken": lambda *_: (_ for _ in ()).throw(RuntimeError("boom"))})

    result = engine.run(RuleContext(filing_type=FilingType.NOE))

    assert result.exit_code == 2
    assert result.findings[0].status is FindingStatus.WARNING
    assert result.findings[0].confidence.value == "low"
