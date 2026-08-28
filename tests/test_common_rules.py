"""Tests for the first source-cited common technical rule pack."""

from __future__ import annotations

from pathlib import Path

from ceqa_preflight.models import Confidence, FilingType, Finding
from ceqa_preflight.pdf_inspector import PdfInspection
from ceqa_preflight.rule_catalog import load_rule_catalog
from ceqa_preflight.rule_engine import RuleContext, RuleEngine
from ceqa_preflight.rules.common import COMMON_RULES


def _all_findings(documents: object) -> list[Finding]:
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
    return result.findings


def _run(documents: object) -> dict[str, Finding]:
    return {finding.rule_id: finding for finding in _all_findings(documents)}


def _statuses(documents: object) -> dict[str, set[str]]:
    """Every status each rule emitted, since a rule may report more than one outcome."""

    statuses: dict[str, set[str]] = {}
    for finding in _all_findings(documents):
        statuses.setdefault(finding.rule_id, set()).add(finding.status.value)
    return statuses


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


# Every rule whose conclusion comes from PdfInspection rather than from the file
# inventory. Each of these is phrased as an absence or an "all documents" claim, so an
# uninspected document must never be counted toward one.
_INSPECTION_DERIVED_RULES = ("PDF-003", "PDF-006", "PDF-007", "PDF-008")


def _document(path: str, **updates: object) -> dict[str, object]:
    document: dict[str, object] = {
        "path": path,
        "is_pdf": True,
        "signature_is_pdf": True,
        "sha256": path,
        "size_bytes": 2048,
        "category": "Notice of Exemption",
        "inspection": _inspection(),
    }
    document.update(updates)
    return document


def test_a_pdf_that_was_never_inspected_never_produces_a_pass() -> None:
    """A timed-out PDF was not measured, so no check may report it as clean.

    An inspection that timed out carries every absence signal at its default: zero form
    fields, zero embedded files, no JavaScript, no launch action. Those defaults describe
    what was read, which is nothing. Counting them as observations makes the report for a
    package nobody could open byte-identical to the report for a package that is fine.
    """

    statuses = _statuses([_document("notice.pdf", inspection=_inspection(timed_out=True))])

    for rule_id in _INSPECTION_DERIVED_RULES:
        assert "pass" not in statuses[rule_id], rule_id
        assert statuses[rule_id] == {"manual"}, rule_id


def test_an_encrypted_pdf_is_excluded_from_absence_claims_not_folded_into_a_pass() -> None:
    """One readable PDF must not carry an "all clear" that also covers an unreadable one."""

    findings = _run(
        [
            _document("NOE_example_project.pdf"),
            _document("NOE_locked_appendix.pdf", inspection=_inspection(readable=False)),
        ]
    )
    statuses = _statuses(
        [
            _document("NOE_example_project.pdf"),
            _document("NOE_locked_appendix.pdf", inspection=_inspection(readable=False)),
        ]
    )

    assert findings["PDF-002"].status.value == "failure"
    for rule_id in _INSPECTION_DERIVED_RULES:
        # The pass stands for the one document that was read, and the document that was
        # not read is reported rather than silently absorbed.
        assert statuses[rule_id] == {"pass", "manual"}, rule_id
        assert "1 " in findings[rule_id].message, findings[rule_id].message


def test_a_package_with_no_pdfs_passes_no_pdf_check() -> None:
    """Zero PDFs is an empty denominator, not a clean bill of health."""

    statuses = _statuses([{"path": "notes.txt", "is_pdf": False, "size_bytes": 12}])

    for rule_id in ("PDF-001", "PDF-002", *_INSPECTION_DERIVED_RULES):
        assert "pass" not in statuses[rule_id], rule_id


def test_unreadable_form_fields_do_not_pass_the_flattened_form_check() -> None:
    """A PDF whose form dictionary could not be parsed has an unknown field count."""

    statuses = _statuses(
        [_document("NOE_broken_acroform.pdf", inspection=_inspection(form_fields_readable=False))]
    )

    assert "pass" not in statuses["PDF-007"]
    assert statuses["PDF-007"] == {"manual"}


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


def test_an_unresolvable_object_graph_does_not_pass_the_active_content_check() -> None:
    """Issue #54. PDF-006 must not report clean on a graph it could not resolve.

    ``javascript_present=False``, ``launch_action_present=False`` and
    ``embedded_file_count=0`` are what a document with no active content looks like, and
    also what a document whose /Root, /Names or /OpenAction never resolved looks like.
    PDF-006 is the one rule in the catalog whose stated purpose is catching crafted or
    corrupt content, so it is the one rule that must never confuse those two.
    """

    statuses = _statuses(
        [_document("NOE_corrupt_xref.pdf", inspection=_inspection(active_content_readable=False))]
    )

    assert "pass" not in statuses["PDF-006"]
    assert statuses["PDF-006"] == {"manual"}


def test_an_unread_structure_tree_is_not_reported_as_a_missing_one() -> None:
    """The other half of issue #54: absence of a reading is not evidence of absence.

    When /Root does not resolve, ``"/StructTreeRoot" in {}`` is False, and PDF-008 used to
    warn that the document is untagged on the strength of a graph nobody read. The
    inspector now leaves the flag None, which PDF-008 already treats as unexaminable.
    """

    statuses = _statuses(
        [_document("NOE_corrupt_xref.pdf", inspection=_inspection(structure_tree_present=None))]
    )

    assert statuses["PDF-008"] == {"manual"}
