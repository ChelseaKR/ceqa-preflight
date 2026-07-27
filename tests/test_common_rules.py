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
        "structure_tree_present": True,
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
                "size_bytes": 1024,
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


def test_warns_for_fillable_forms_separately_from_active_content() -> None:
    findings = _run(
        [
            {
                "path": "NOE_fillable_form.pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "size_bytes": 2048,
                "inspection": _inspection(
                    active_form_field_count=2,
                    active_form_field_names=["applicant", "project_title"],
                ),
            }
        ]
    )

    assert findings["PDF-007"].status.value == "warning"
    assert findings["PDF-007"].evidence.details["form_field_count"] == 2
    assert findings["PDF-006"].status.value == "pass"


def test_warns_for_missing_structure_tags_without_certifying_accessibility() -> None:
    untagged = _run(
        [
            {
                "path": "NOE_untagged_scan.pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "size_bytes": 2048,
                "inspection": _inspection(structure_tree_present=False),
            }
        ]
    )
    unknown = _run(
        [
            {
                "path": "NOE_unknown_tags.pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "size_bytes": 2048,
                "inspection": _inspection(structure_tree_present=None),
            }
        ]
    )

    assert untagged["PDF-008"].status.value == "warning"
    assert "not accessibility certification" in untagged["PDF-008"].message
    assert unknown["PDF-008"].status.value == "manual"


def test_warns_for_large_files_and_marks_unknown_sizes_manual() -> None:
    large = _run(
        [
            {
                "path": "NOE_large_appendix.pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "size_bytes": 60 * 1024 * 1024,
                "inspection": _inspection(),
            }
        ]
    )
    unknown = _run(
        [
            {
                "path": "NOE_unknown_size.pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "inspection": _inspection(),
            }
        ]
    )

    assert large["FILE-004"].status.value == "warning"
    assert large["FILE-004"].evidence.details["size_bytes"] == 60 * 1024 * 1024
    assert "no official size limit is documented" in large["FILE-004"].remediation
    assert unknown["FILE-004"].status.value == "manual"


def test_warns_for_convertible_non_pdf_documents_but_not_manifests() -> None:
    findings = _run(
        [
            {
                "path": "NOE_example_project.pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "size_bytes": 2048,
                "inspection": _inspection(),
            },
            {"path": "NOE_source_form.docx", "is_pdf": False, "size_bytes": 2048},
            {"path": "package.yaml", "is_pdf": False, "size_bytes": 100},
        ]
    )

    assert findings["FILE-003"].status.value == "warning"
    assert findings["FILE-003"].evidence.details["non_pdf_documents"] == ["NOE_source_form.docx"]


def test_warns_for_unportable_or_overlong_filenames() -> None:
    findings = _run(
        [
            {
                "path": "NOE_project#draft?.pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "size_bytes": 2048,
                "inspection": _inspection(),
            },
            {
                "path": ("x" * 160) + ".pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "size_bytes": 2048,
                "inspection": _inspection(),
            },
        ]
    )

    assert findings["FILE-005"].status.value == "warning"
    assert findings["FILE-005"].evidence.details["filenames"] == [
        "NOE_project#draft?.pdf",
        ("x" * 160) + ".pdf",
    ]


def test_zero_text_coverage_suggests_ocr() -> None:
    findings = _run(
        [
            {
                "path": "NOE_scanned_notice.pdf",
                "is_pdf": True,
                "signature_is_pdf": True,
                "size_bytes": 2048,
                "inspection": _inspection(extracted_characters={1: 0}, text_coverage=0.0),
            }
        ]
    )

    assert findings["PDF-003"].status.value == "warning"
    assert "scanned image" in findings["PDF-003"].message
    assert "optical character recognition" in findings["PDF-003"].remediation
