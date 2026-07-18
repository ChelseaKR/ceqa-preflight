"""End-to-end local package check and report rendering tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter

from ceqa_preflight.checker import check_package
from ceqa_preflight.models import FilingType, PackageManifest
from ceqa_preflight.reporting import render_console, render_html, render_json


def _package(tmp_path: Path) -> tuple[Path, PackageManifest]:
    package = tmp_path / "package"
    package.mkdir()
    document = package / "NOE_example.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with document.open("wb") as output:
        writer.write(output)
    manifest = PackageManifest.model_validate(
        {
            "filing_type": "NOE",
            "project": {"title": "Example Project"},
            "documents": [
                {
                    "path": "NOE_example.pdf",
                    "category": "Notice of Exemption",
                    "primary": True,
                }
            ],
        }
    )
    return package, manifest


def test_check_package_is_local_and_returns_source_cited_report(tmp_path: Path) -> None:
    package, manifest = _package(tmp_path)
    original_hash = (package / "NOE_example.pdf").read_bytes()

    report, exit_code = check_package(package, FilingType.NOE, manifest=manifest)

    assert exit_code == 0
    assert report.filing_type is FilingType.NOE
    assert report.input_fingerprint
    assert (package / "NOE_example.pdf").read_bytes() == original_hash
    assert {finding.rule_id for finding in report.manual_review} == {
        "NOE-M001",
        "NOE-M002",
        "NOE-M003",
    }
    assert all(finding.source is not None for finding in [*report.findings, *report.manual_review])
    assert "CEQA Preflight advisory report" in render_console(report)
    assert '"input_fingerprint"' in render_json(report)
    html = render_html(report)
    assert '<html lang="en">' in html
    assert "Manual review" in html
    assert "<script" not in html


def test_manifest_filing_type_must_match_requested_type(tmp_path: Path) -> None:
    package, manifest = _package(tmp_path)

    with pytest.raises(ValueError, match="does not match"):
        check_package(package, FilingType.NOD, manifest=manifest)
