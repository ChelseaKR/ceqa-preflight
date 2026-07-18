"""Tests for the first source-cited common technical rule pack."""

from __future__ import annotations

from pathlib import Path

from ceqa_preflight.models import Confidence, FilingType, Finding
from ceqa_preflight.pdf_inspector import PdfInspection
from ceqa_preflight.rule_catalog import load_rule_catalog
from ceqa_preflight.rule_engine import RuleContext, RuleEngine
from ceqa_preflight.rules.common import COMMON_RULES


def _run(documents: object) -> dict[str, Finding]:
    root = Path(__file__).parents[1]
    catalog = load_rule_catalog([root / "src/ceqa_preflight/rulepacks/common.yaml"])
    facts: dict[str, object] = {"documents": documents}
    if isinstance(documents, list):
        facts["declared_paths"] = [
            item["path"]
            for item in documents
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        ]
    result = RuleEngine(catalog, COMMON_RULES).run(
        RuleContext(filing_type=FilingType.NOE, facts=facts)
    )
    assert result.exit_code == 0
    return {finding.rule_id: finding for finding in result.findings}


def _inspection(**updates: object) -> PdfInspection:
    values: dict[str, object] = {
        "readable": True,
        "sampled_pages": [1],
        "extracted_characters": {1: 30},
        "text_coverage": 1.0,
        "extraction_confidence": Confidence.HIGH,
    }
    values.update(updates)
    return PdfInspection.model_validate(values)


def test_passes_complete_pdf_package() -> None:
    findings = _run(
        [
            {
                "path": "NOE_example_project.pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "sha256": "a" * 64,
                "category": "Notice of Exemption",
                "inspection": _inspection(),
            }
        ]
    )

    assert {finding.status.value for finding in findings.values()} == {"pass"}


def test_reports_missing_and_spoofed_pdfs() -> None:
    missing = _run([])
    spoofed = _run(
        [
            {
                "path": "notice.pdf",
                "is_pdf": True,
                "signature_is_pdf": False,
                "inspection": _inspection(),
            }
        ]
    )

    assert missing["CORE-001"].status.value == "failure"
    assert spoofed["PDF-001"].status.value == "failure"


def test_warns_for_low_coverage_and_active_content() -> None:
    findings = _run(
        [
            {
                "path": "notice.pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "inspection": _inspection(
                    text_coverage=0.5,
                    active_form_field_count=1,
                    embedded_file_count=1,
                    javascript_present=True,
                ),
            }
        ]
    )

    assert findings["PDF-003"].status.value == "warning"
    assert findings["PDF-006"].status.value == "warning"
    assert findings["PDF-003"].evidence.details["threshold"] == 0.8


def test_maps_incomplete_or_timed_out_facts_to_manual_review() -> None:
    incomplete = _run({"not": "a list"})
    timed_out = _run(
        [
            {
                "path": "notice.pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "inspection": _inspection(timed_out=True),
            }
        ]
    )

    assert {finding.status.value for finding in incomplete.values()} == {"manual"}
    assert timed_out["PDF-002"].status.value == "manual"


def test_warns_on_duplicate_hashes() -> None:
    findings = _run(
        [
            {
                "path": "first.pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "sha256": "same",
                "inspection": _inspection(),
            },
            {
                "path": "second.pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "sha256": "same",
                "inspection": _inspection(),
            },
        ]
    )

    assert findings["FILE-002"].status.value == "warning"
    assert findings["FILE-002"].evidence.details["duplicate_groups"] == [
        ["first.pdf", "second.pdf"]
    ]


def test_warns_for_uncategorized_or_weakly_named_files_and_fails_missing_manifest_path() -> None:
    root = Path(__file__).parents[1]
    catalog = load_rule_catalog([root / "src/ceqa_preflight/rulepacks/common.yaml"])
    result = RuleEngine(catalog, COMMON_RULES).run(
        RuleContext(
            filing_type=FilingType.NOE,
            facts={
                "documents": [
                    {
                        "path": "1.pdf",
                        "is_pdf": True,
                        "signature_is_pdf": True,
                        "inspection": _inspection(),
                    }
                ],
                "declared_paths": ["1.pdf", "missing.pdf"],
            },
        )
    )
    findings = {finding.rule_id: finding for finding in result.findings}

    assert findings["FILE-001"].status.value == "warning"
    assert findings["CAT-001"].status.value == "warning"
    assert findings["MAN-001"].status.value == "failure"
