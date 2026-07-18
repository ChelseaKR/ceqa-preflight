"""Tests for conservative NOD and NOE filing-form rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from ceqa_preflight.models import Confidence, FilingType, Finding
from ceqa_preflight.pdf_inspector import PdfInspection
from ceqa_preflight.rule_catalog import load_rule_catalog
from ceqa_preflight.rule_engine import RuleContext, RuleEngine
from ceqa_preflight.rules.nod import NOD_RULES
from ceqa_preflight.rules.noe import NOE_RULES


def _inspection(**updates: object) -> PdfInspection:
    values: dict[str, object] = {
        "readable": True,
        "extraction_confidence": Confidence.HIGH,
    }
    values.update(updates)
    return PdfInspection.model_validate(values)


def _run(filing_type: FilingType, documents: object) -> dict[str, Finding]:
    root = Path(__file__).parents[1]
    pack = "nod.yaml" if filing_type is FilingType.NOD else "noe.yaml"
    registry = NOD_RULES if filing_type is FilingType.NOD else NOE_RULES
    catalog = load_rule_catalog([root / "src/ceqa_preflight/rulepacks" / pack])
    result = RuleEngine(catalog, registry).run(
        RuleContext(filing_type=filing_type, facts={"documents": documents}),
        include_experimental=True,
    )
    assert result.exit_code == 0
    return {finding.rule_id: finding for finding in result.findings}


@pytest.mark.parametrize(
    ("filing_type", "category", "prefix"),
    [
        (FilingType.NOD, "Notice of Determination", "NOD"),
        (FilingType.NOE, "Notice of Exemption", "NOE"),
    ],
)
def test_declared_primary_form_passes_and_legal_questions_stay_manual(
    filing_type: FilingType, category: str, prefix: str
) -> None:
    findings = _run(
        filing_type,
        [
            {
                "path": f"{prefix}_form.pdf",
                "is_pdf": True,
                "primary": True,
                "category": category,
                "inspection": _inspection(),
            }
        ],
    )

    assert [findings[f"{prefix}-00{number}"].status.value for number in range(1, 4)] == [
        "pass",
        "pass",
        "pass",
    ]
    assert {findings[f"{prefix}-M00{number}"].status.value for number in range(1, 4)} == {"manual"}


@pytest.mark.parametrize(
    ("filing_type", "category", "prefix"),
    [
        (FilingType.NOD, "Notice of Determination", "NOD"),
        (FilingType.NOE, "Notice of Exemption", "NOE"),
    ],
)
def test_missing_multiple_and_unclassified_primary_forms_are_safe(
    filing_type: FilingType, category: str, prefix: str
) -> None:
    missing = _run(filing_type, [])
    multiple = _run(
        filing_type,
        [
            {"path": "one.pdf", "is_pdf": True, "primary": True, "category": category},
            {"path": "two.pdf", "is_pdf": True, "primary": True, "category": category},
        ],
    )
    unknown = _run(
        filing_type,
        [{"path": "unknown.pdf", "is_pdf": True, "primary": True}],
    )

    assert missing[f"{prefix}-001"].status.value == "failure"
    assert multiple[f"{prefix}-001"].status.value == "failure"
    assert unknown[f"{prefix}-001"].status.value == "manual"
    assert unknown[f"{prefix}-002"].status.value == "manual"


@pytest.mark.parametrize(
    ("filing_type", "category", "prefix"),
    [
        (FilingType.NOD, "Notice of Determination", "NOD"),
        (FilingType.NOE, "Notice of Exemption", "NOE"),
    ],
)
def test_unreadable_primary_form_fails(filing_type: FilingType, category: str, prefix: str) -> None:
    findings = _run(
        filing_type,
        [
            {
                "path": "form.pdf",
                "is_pdf": True,
                "primary": True,
                "category": category,
                "inspection": _inspection(readable=False, encrypted=True),
            }
        ],
    )

    assert findings[f"{prefix}-002"].status.value == "failure"
