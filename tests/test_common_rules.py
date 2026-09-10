"""Tests for the first source-cited common technical rule pack."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ceqa_preflight import pdf_inspector
from ceqa_preflight.checker import check_package
from ceqa_preflight.models import Confidence, FilingType, Finding
from ceqa_preflight.pdf_inspector import PdfInspection
from ceqa_preflight.rule_catalog import load_rule_catalog
from ceqa_preflight.rule_engine import RuleContext, RuleEngine
from ceqa_preflight.rules.common import (
    COMMON_RULES,
    DocumentFact,
    NotExamined,
    _examined,
    _excluded_message,
)
from ceqa_preflight.synth import SyntheticDefect, write_synthetic_package


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


def test_an_inspection_that_never_answered_is_not_a_verdict_about_the_document() -> None:
    """The three `readable=False` states are not one state, and one of them is not evidence.

    A timeout, a worker that produced no result, and a worker that reported its own failure
    all arrive carrying `readable=False` -- and so does a document that was fully parsed and
    found genuinely corrupt or encrypted. Only the last is a measurement. Before
    `PdfInspection.completed` existed, the first two fell past the `timed_out` guard into
    the branch below it and PDF-002 published *"This PDF is unreadable or encrypted."*
    about a document nothing had read: a claim about the filer's file made on the strength
    of a fact about the machine that ran the check.
    """

    corrupt = _run([_document("notice.pdf", inspection=_inspection(readable=False))])
    never_answered = _run(
        [_document("notice.pdf", inspection=_inspection(readable=False, completed=False))]
    )
    timed_out = _run(
        [
            _document(
                "notice.pdf",
                inspection=_inspection(readable=False, completed=False, timed_out=True),
            )
        ]
    )

    assert corrupt["PDF-002"].status.value == "failure"
    assert "unreadable or encrypted" in corrupt["PDF-002"].message

    assert never_answered["PDF-002"].status.value == "manual"
    assert "the inspection did not complete" in never_answered["PDF-002"].message
    assert "unreadable or encrypted" not in never_answered["PDF-002"].message

    # And the two gaps stay apart from each other: a timeout says which limit was hit.
    assert timed_out["PDF-002"].status.value == "manual"
    assert "within the safe limit" in timed_out["PDF-002"].message


def test_an_inspection_that_never_answered_produces_no_pass_anywhere() -> None:
    """The same rule the timeout case already holds, for the state that had escaped it."""

    statuses = _statuses(
        [_document("notice.pdf", inspection=_inspection(readable=False, completed=False))]
    )

    for rule_id in _INSPECTION_DERIVED_RULES:
        assert statuses[rule_id] == {"manual"}, rule_id


def test_the_real_inspector_results_carry_the_flag_the_rules_read() -> None:
    """The coupling. Every case above builds its inspection by hand.

    If `pdf_inspector` stopped setting `completed=False` on the results it constructs when
    the worker does not answer, every assertion above would stay green while PDF-002 went
    back to calling an uninspected document unreadable. These are the three producers.
    """

    assert pdf_inspector._timeout_result().completed is False
    assert pdf_inspector._no_result_from_worker().completed is False
    assert pdf_inspector._receive_inspection(_BrokenConnection()).completed is False


class _BrokenConnection:
    """A worker that reported its own failure, which is the third producer."""

    def recv(self) -> object:
        return {"error": "PDF inspection worker failed"}


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


def test_an_empty_package_produces_no_passing_check_at_all() -> None:
    """An empty package is an empty denominator for every rule, not a clean bill of health.

    ``_conclude`` was written so "a pass can never come from an empty denominator", but the
    six package-level rules did not use it: FILE-001 through FILE-005 and CAT-001 each
    returned a bare PASS when their population was empty. A directory containing nothing
    produced six green lines saying filenames were portable, no duplicates were found, and
    every PDF had a category, none of which had been measured against a single file.
    """

    statuses = _statuses([])

    passed = sorted(rule_id for rule_id, values in statuses.items() if "pass" in values)
    assert passed == [], f"these rules passed with nothing to examine: {passed}"


def test_a_package_of_only_non_pdf_files_passes_no_pdf_scoped_check() -> None:
    """PDF-scoped rules must not pass on a package that contains no PDF."""

    # A suffix outside _CONVERTIBLE_SUFFIXES, so FILE-003 has nothing to warn about here.
    statuses = _statuses(
        [{"path": "checksums.sig", "is_pdf": False, "sha256": "n" * 64, "size_bytes": 9}]
    )

    for rule_id in ("FILE-001", "CAT-001"):
        assert "pass" not in statuses[rule_id], rule_id
    # File-scoped rules did examine the one real file, so they may still pass, and their
    # pass message has to say how many files it stands for.
    for rule_id in ("FILE-003", "FILE-004", "FILE-005"):
        assert "pass" in statuses[rule_id], rule_id


def test_a_file_with_no_checksum_is_disclosed_not_folded_into_the_duplicate_pass() -> None:
    """FILE-002 can only speak for the files it actually hashed."""

    statuses = _statuses(
        [
            {"path": "a.pdf", "is_pdf": True, "sha256": "a" * 64, "size_bytes": 10},
            {"path": "b.pdf", "is_pdf": True, "sha256": None, "size_bytes": 10},
        ]
    )

    assert statuses["FILE-002"] == {"pass", "manual"}


# --------------------------------------------------------------------------------------
# Why a document was left out of a check
# --------------------------------------------------------------------------------------
#
# Measured on `origin/main` before this change, over the synthetic NOE package seeded with
# `encrypted`, `unreadable` and `bad-signature` (three documents left out for three
# different reasons):
#
#   PDF-003 | 3 PDF document(s) could not be inspected and were excluded from this check,
#   PDF-006 |   which therefore makes no statement about them.
#   PDF-007 | (same sentence)
#   PDF-008 | (same sentence)
#   PDF-002 | A PDF could not be fully inspected within the safe limit.
#
# Four rules published one sentence about three different facts, and PDF-002 published a
# timeout about a file nothing had opened: the checker inspects a `.pdf` only once its
# leading bytes carry a PDF signature (`checker.py`, `if is_pdf and signature_is_pdf`), so
# the bad-signature file never reached a clock to run out of. No test and no document in
# the repository asserted either sentence, which is why splitting them turned nothing red.


def _messages(documents: object) -> dict[str, list[str]]:
    """Every message each rule emitted, in the order it emitted them."""

    messages: dict[str, list[str]] = {}
    for finding in _all_findings(documents):
        messages.setdefault(finding.rule_id, []).append(finding.message)
    return messages


# One document per reason, and the reason each one must be reported under. The mapping is
# checked for completeness against `NotExamined` below, so a sixth reason cannot be added
# without a case that produces it.
_EXCLUSION_CASES: dict[NotExamined, dict[str, object]] = {
    # A `.pdf` whose leading bytes are not a PDF signature. The checker never opens it, so
    # it carries no inspection at all.
    NotExamined.NOT_INSPECTED: _document(
        "NOE_not_really_a_pdf.pdf", signature_is_pdf=False, inspection=None
    ),
    # The worker died, timed out, or reported its own failure. A fact about this machine.
    NotExamined.INSPECTION_UNFINISHED: _document(
        "NOE_worker_never_answered.pdf", inspection=_inspection(readable=False, completed=False)
    ),
    # Opened and refused. A measurement about the filer's file.
    NotExamined.DOCUMENT_UNREADABLE: _document(
        "NOE_locked_appendix.pdf", inspection=_inspection(readable=False)
    ),
    # Opened, and the part this check needs did not resolve. All four per-signal flags are
    # set at once so every inspection-derived rule reaches the same reason from one case.
    NotExamined.SIGNAL_UNREADABLE: _document(
        "NOE_corrupt_xref.pdf",
        inspection=_inspection(
            text_coverage=None,
            active_content_readable=False,
            form_fields_readable=False,
            structure_tree_present=None,
        ),
    ),
    # Facts that reached the rules without a signature reading. `checker.py` always records
    # one for a `.pdf`, so this arrives from another producer of the `documents` fact --
    # a rule pack, a replayed report, a caller of the public rule engine.
    NotExamined.SIGNATURE_NOT_RECORDED: _document(
        "NOE_signature_unrecorded.pdf", signature_is_pdf=None
    ),
}


def test_every_exclusion_reason_has_a_case_that_produces_it() -> None:
    """The self-limiting half: a reason nothing produces is a sentence nobody has read.

    Without this, `NotExamined` can grow a member whose sentence is never rendered by any
    test, and the first reader to meet it is a filer.
    """

    assert set(_EXCLUSION_CASES) == set(NotExamined)


def test_each_reason_a_document_is_left_out_is_disclosed_in_its_own_words() -> None:
    """Five facts, five sentences, five remedies -- not one sentence five times.

    "N PDF document(s) could not be inspected" was true of a file the tool never opened, a
    file it opened and could not read, a file it read where one signal did not resolve, and
    a run where the inspection worker died. Those have four different remedies and one of
    them is not about the package at all.
    """

    seen: dict[NotExamined, tuple[str, str]] = {}
    for reason in NotExamined:
        message, remediation = _excluded_message(reason, 1)
        assert message.strip(), reason
        assert remediation.strip(), reason
        seen[reason] = (message, remediation)

    assert len(set(seen.values())) == len(NotExamined), (
        f"two exclusion reasons share a sentence or a remedy: {seen}"
    )
    assert len({message for message, _remediation in seen.values()}) == len(NotExamined)
    assert len({remediation for _message, remediation in seen.values()}) == len(NotExamined)


def test_an_exclusion_reason_with_no_sentence_is_refused_not_given_the_last_one() -> None:
    """The trailing-`return` trap, asserted rather than described.

    A final unconditional `return` reads exactly like a match for the last member, so a new
    reason would be published under the previous one's sentence *and* its remedy -- telling
    a filer to re-run the check so the inventory records a signature, about a document
    whose signature was recorded. `_excluded_message` matches every member by name.
    """

    with pytest.raises(ValueError, match="no disclosure sentence"):
        _excluded_message("a reason added without a sentence", 1)  # type: ignore[arg-type]


def test_the_four_absence_rules_report_each_reason_separately_in_one_package() -> None:
    """The whole package at once, which is how a filer meets it.

    One document per reason, so each inspection-derived rule must emit one manual-review
    line per reason rather than a single count over all of them.
    """

    package = list(_EXCLUSION_CASES.values())
    messages = _messages(package)
    sentence = {reason: _excluded_message(reason, 1)[0] for reason in NotExamined}

    # SIGNATURE_NOT_RECORDED is PDF-001's alone: no other rule reads that field. The one
    # healthy document in the package is the signature case, so each rule also passes for
    # exactly that one, and the pass has to stand beside the gaps rather than absorb them.
    inspection_reasons = [
        reason for reason in NotExamined if reason is not NotExamined.SIGNATURE_NOT_RECORDED
    ]
    for rule_id in _INSPECTION_DERIVED_RULES:
        emitted = messages[rule_id]
        disclosed = [reason for reason in NotExamined if sentence[reason] in emitted]
        assert disclosed == inspection_reasons, f"{rule_id}: {emitted}"
        # Nothing else was said: one pass for the one examined document, four gaps.
        assert len(emitted) == len(inspection_reasons) + 1, emitted
        assert " 1 inspected PDF(s)" in emitted[0], emitted[0]

    assert sentence[NotExamined.SIGNATURE_NOT_RECORDED] in messages["PDF-001"]


def test_a_document_that_was_never_opened_is_not_reported_as_a_timeout() -> None:
    """The live wrong claim this replaces, in the rule that published it.

    PDF-002 said *"A PDF could not be fully inspected within the safe limit."* about a file
    with no inspection at all. Nothing ran out of clock: `checker.py` opens a `.pdf` as a
    PDF only once its leading bytes carry a PDF signature, so a bad-signature file is one
    the tool declined to open, and the remedy is PDF-001's, not a longer timeout.
    """

    never_opened = _messages([_EXCLUSION_CASES[NotExamined.NOT_INSPECTED]])["PDF-002"]
    timed_out = _messages([_document("NOE_slow.pdf", inspection=_inspection(timed_out=True))])[
        "PDF-002"
    ]

    assert "within the safe limit" not in " ".join(never_opened), never_opened
    assert _excluded_message(NotExamined.NOT_INSPECTED, 1)[0] in never_opened
    # And the sentence that is about a clock still belongs to the case that has one.
    assert any("within the safe limit" in message for message in timed_out), timed_out


def test_the_reason_a_document_is_left_out_is_read_off_the_inspection_not_guessed() -> None:
    """The coupling test. Every case above builds its `DocumentFact` by hand.

    Three of the five reasons are decided in one place, `_examined`, and this pins that
    mapping directly: if it stopped separating "the worker never answered" from "the
    document is damaged", every assertion above would still pass through whichever branch
    absorbed the other.

    The other two are decided elsewhere on purpose and are named here so the split is
    written down rather than inferred: `SIGNAL_UNREADABLE` belongs to the rule that
    consumes the signal (a document can be perfectly readable and still have an
    unresolvable form dictionary), and `SIGNATURE_NOT_RECORDED` is an inventory fact
    PDF-001 reads without an inspection at all.
    """

    decided_by_examined = {
        NotExamined.NOT_INSPECTED,
        NotExamined.INSPECTION_UNFINISHED,
        NotExamined.DOCUMENT_UNREADABLE,
    }
    decided_elsewhere = {NotExamined.SIGNAL_UNREADABLE, NotExamined.SIGNATURE_NOT_RECORDED}
    assert decided_by_examined | decided_elsewhere == set(NotExamined)

    for reason in decided_by_examined:
        fact = DocumentFact.model_validate(_EXCLUSION_CASES[reason])
        assert _examined(fact) is reason, (fact.path, reason)

    # A complete, readable inspection is not a reason at all -- it is the inspection, and
    # that is exactly why the per-signal cases have to be caught by their own rules.
    for reason in decided_elsewhere:
        fact = DocumentFact.model_validate(_EXCLUSION_CASES[reason])
        assert isinstance(_examined(fact), PdfInspection), (fact.path, reason)
    assert isinstance(
        _examined(DocumentFact.model_validate(_document("NOE_fine.pdf"))), PdfInspection
    )


def test_the_real_inspector_produces_the_state_each_reason_is_read_from() -> None:
    """The other half of the coupling: these are `pdf_inspector`'s own results.

    `INSPECTION_UNFINISHED` is only ever correct if the producers really do set
    `completed=False`; `DOCUMENT_UNREADABLE` is only ever correct if a completed inspection
    of a locked file really does come back readable=False with completed=True.
    """

    assert (
        _examined(
            DocumentFact.model_validate(
                _document("x.pdf", inspection=pdf_inspector._timeout_result())
            )
        )
        is NotExamined.INSPECTION_UNFINISHED
    )
    assert (
        _examined(
            DocumentFact.model_validate(
                _document("x.pdf", inspection=pdf_inspector._no_result_from_worker())
            )
        )
        is NotExamined.INSPECTION_UNFINISHED
    )


def test_the_end_to_end_check_of_a_bad_signature_package_names_the_right_gap() -> None:
    """The production path, not a hand-built fact.

    `synth --defect bad-signature` writes a `.pdf` whose leading bytes are not a PDF
    signature -- the one input that reaches `inspection is None` through `checker.py`. This
    is what makes the reason reachable in a real run rather than only in this module.
    """

    with tempfile.TemporaryDirectory() as scratch:
        package = Path(scratch) / "package"
        write_synthetic_package(package, FilingType.NOE, [SyntheticDefect.BAD_SIGNATURE])
        report, _exit_code = check_package(package, FilingType.NOE)

    manual = [finding for finding in report.manual_review if finding.rule_id == "PDF-002"]
    assert manual, [finding.rule_id for finding in report.manual_review]
    assert all("within the safe limit" not in finding.message for finding in manual), manual
    assert any(
        finding.message == _excluded_message(NotExamined.NOT_INSPECTED, 1)[0] for finding in manual
    ), [finding.message for finding in manual]
