"""Synthetic package generation and end-to-end defect detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from ceqa_preflight.checker import check_package
from ceqa_preflight.manifest import load_manifest
from ceqa_preflight.models import FilingType
from ceqa_preflight.synth import SyntheticDefect, write_synthetic_package


def _statuses_by_rule(directory: Path, filing_type: FilingType) -> dict[str, set[str]]:
    manifest = load_manifest(directory / "package.yaml")
    report, _ = check_package(directory, filing_type, manifest=manifest, include_experimental=True)
    statuses: dict[str, set[str]] = {}
    for finding in [*report.findings, *report.manual_review]:
        statuses.setdefault(finding.rule_id, set()).add(finding.status.value)
    return statuses


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

    statuses = _statuses_by_rule(directory, FilingType.NOD)

    assert "failure" in statuses["PDF-001"]  # bad signature
    assert "failure" in statuses["PDF-002"]  # encrypted and unreadable
    assert "warning" in statuses["PDF-003"]  # scanned, no searchable text
    assert "warning" in statuses["PDF-007"]  # fillable form
    assert "warning" in statuses["FILE-001"]  # weak filename
    assert "warning" in statuses["FILE-002"]  # duplicate hashes
    assert "warning" in statuses["FILE-003"]  # non-PDF document
    assert "failure" in statuses["MAN-001"]  # missing manifest reference
