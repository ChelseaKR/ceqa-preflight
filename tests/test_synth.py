"""Synthetic package generation and end-to-end defect detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from ceqa_preflight.checker import check_package
from ceqa_preflight.limits import PackageLimits
from ceqa_preflight.manifest import load_manifest
from ceqa_preflight.models import FilingType, Finding, InspectionReport
from ceqa_preflight.synth import SyntheticDefect, write_synthetic_package

#: The bound this test inspects under, in place of ``DEFAULT_PACKAGE_LIMITS``.
#:
#: ``inspect_pdf`` runs each document in a spawned process under a wall clock, and
#: three outcomes -- a timeout, a worker error, a worker that sent nothing -- all
#: produce an inspection with ``completed=False`` and therefore no
#: ``text_coverage``. The rules read that, correctly, as a document they could not
#: examine, and report it for manual review rather than concluding. So on a loaded
#: shared runner the seeded scanned PDF could arrive as ``manual`` instead of
#: ``warning`` and the test failed on a document nothing had actually read
#: (issue #113).
#:
#: The bound is not raised: the *production* default is untouched, and this is not
#: a performance assertion. These are synthetic PDFs of a few kilobytes whose
#: inspection is a matter of milliseconds; the bound is here so a genuinely hung
#: worker still fails the suite rather than hanging it. Everything else about the
#: limits stays at the shipped values, so the package-expansion guards this test
#: runs through are the ones a user gets.
INSPECTION_BOUND = PackageLimits(per_file_timeout_seconds=600.0)

#: The document ``SyntheticDefect.SCANNED`` writes, named here so the PDF-003
#: assertion can say *which* document it expects a warning about. Spelled as a
#: literal rather than read back out of ``synth.py``: a fixture computed from the
#: code under test moves with it and can never catch it moving.
SCANNED_DOCUMENT = "Fictional_Example_Project_scanned_notice.pdf"


def _check(directory: Path, filing_type: FilingType) -> InspectionReport:
    manifest = load_manifest(directory / "package.yaml")
    report, _ = check_package(
        directory,
        filing_type,
        manifest=manifest,
        include_experimental=True,
        limits=INSPECTION_BOUND,
    )
    return report


def _findings(report: InspectionReport) -> list[Finding]:
    return [*report.findings, *report.manual_review]


def _uninspectable(report: InspectionReport) -> list[str]:
    """Every finding saying some PDF could not be inspected, as readable lines.

    ``_conclude`` in ``rules/common.py`` emits one of these whenever a per-document
    check had to exclude a document, which is what an inspection that did not
    complete produces -- and also what a genuinely unreadable document produces.
    This fixture seeds both an encrypted and a truncated PDF on purpose, so these
    lines are *expected* here and are not on their own a failure. They are collected
    because they are the only place the report says anything about a document
    nothing could read, and a run where the seeded scanned notice joined them is
    exactly the run this test used to fail on for the wrong reason.
    """
    return [
        f"{finding.rule_id} [{finding.status.value}]: {finding.message}"
        for finding in _findings(report)
        if "could not be inspected" in finding.message
    ]


def _why(report: InspectionReport, rule_id: str) -> str:
    """An assertion message that names the path a failing run took.

    The bare ``assert "warning" in statuses["PDF-003"]`` cost a whole investigation
    because ``{'manual', 'pass'}`` says nothing about *why* the rule did not fire.
    """
    lines = [f"{rule_id} produced: {sorted(_statuses(report, rule_id))}"]
    lines += [
        f"  {finding.status.value} on {finding.document or '(no document)'}: {finding.message}"
        for finding in _for(report, rule_id)
    ]
    excluded = _uninspectable(report)
    if excluded:
        lines.append(
            "Some PDF was excluded as uninspectable. The encrypted and truncated documents "
            "this fixture seeds are expected here; any other document in this list did not "
            "finish being inspected, and every assertion about it is then reading the "
            "absence of a reading rather than the presence of a defect:"
        )
        lines += [f"  {line}" for line in excluded]
    return "\n".join(lines)


def _for(report: InspectionReport, rule_id: str) -> list[Finding]:
    return [finding for finding in _findings(report) if finding.rule_id == rule_id]


def _statuses(report: InspectionReport, rule_id: str) -> set[str]:
    return {finding.status.value for finding in _for(report, rule_id)}


def _documents_with(report: InspectionReport, rule_id: str, status: str) -> set[str]:
    return {
        finding.document
        for finding in _for(report, rule_id)
        if finding.status.value == status and finding.document
    }


def test_clean_synthetic_package_passes_all_automated_checks(tmp_path: Path) -> None:
    directory = tmp_path / "clean"
    created = write_synthetic_package(directory, FilingType.NOE, [])

    assert (directory / "package.yaml") in created
    banner = (directory / "NOE_Fictional_Example_Project_form.pdf").read_bytes()
    assert b"Synthetic CEQA Preflight test data" in banner

    manifest = load_manifest(directory / "package.yaml")
    report, exit_code = check_package(
        directory, FilingType.NOE, manifest=manifest, include_experimental=True
    )

    assert exit_code == 0
    assert all(finding.status.value == "pass" for finding in report.findings)


def test_refuses_non_empty_directories(tmp_path: Path) -> None:
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "existing.txt").write_text("existing", encoding="utf-8")
    blocked = tmp_path / "blocked.txt"
    blocked.write_text("not a directory", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_synthetic_package(occupied, FilingType.NOE, [])
    with pytest.raises(ValueError, match="must be a directory"):
        write_synthetic_package(blocked, FilingType.NOE, [])


def test_each_seeded_defect_is_detected_by_its_rule(tmp_path: Path) -> None:
    directory = tmp_path / "defects"
    write_synthetic_package(
        directory,
        FilingType.NOD,
        [
            SyntheticDefect.ENCRYPTED,
            SyntheticDefect.UNREADABLE,
            SyntheticDefect.SCANNED,
            SyntheticDefect.FILLABLE_FORM,
            SyntheticDefect.DUPLICATE,
            SyntheticDefect.NON_PDF,
            SyntheticDefect.BAD_SIGNATURE,
            SyntheticDefect.WEAK_FILENAME,
            SyntheticDefect.MISSING_MANIFEST_REFERENCE,
        ],
    )

    report = _check(directory, FilingType.NOD)

    for rule_id, expected in (
        ("PDF-001", "failure"),  # bad signature
        ("PDF-002", "failure"),  # encrypted and unreadable
        ("PDF-003", "warning"),  # scanned, no searchable text
        ("PDF-007", "warning"),  # fillable form
        ("FILE-001", "warning"),  # weak filename
        ("FILE-002", "warning"),  # duplicate hashes
        ("FILE-003", "warning"),  # non-PDF document
        ("MAN-001", "failure"),  # missing manifest reference
    ):
        assert expected in _statuses(report, rule_id), _why(report, rule_id)

    # And PDF-003 warned about *the scanned notice*, not merely about something.
    # `"warning" in statuses` is satisfied by a warning on any document, so it would
    # survive the scanned PDF dropping out as long as some other PDF was also below
    # the threshold. This is the assertion the flake was really about.
    assert SCANNED_DOCUMENT in _documents_with(report, "PDF-003", "warning"), _why(
        report, "PDF-003"
    )
