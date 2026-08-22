"""End-to-end local package check and report rendering tests."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pytest_socket import SocketBlockedError

from ceqa_preflight.checker import check_package
from ceqa_preflight.models import (
    FilingType,
    FindingStatus,
    PackageManifest,
    SkipReason,
    SourceKind,
)
from ceqa_preflight.reporting import (
    render_checklist,
    render_console,
    render_html,
    render_json,
)


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

    report, exit_code = check_package(
        package,
        FilingType.NOE,
        manifest=manifest,
        include_experimental=True,
    )

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


@pytest.mark.filterwarnings("ignore:A test tried to use socket.socket")
def test_the_suite_actually_blocks_network_access() -> None:
    """Guard the guard: prove --disable-socket is in effect for this run.

    The README promises the tool makes no network requests at runtime. pytest-socket is
    what holds that promise to account, but it only does so while `--disable-socket` is in
    addopts; drop the flag and the whole suite goes on passing while the promise quietly
    stops being enforced. This test fails in that case.
    """

    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_manifest_filing_type_must_match_requested_type(tmp_path: Path) -> None:
    package, manifest = _package(tmp_path)

    with pytest.raises(ValueError, match="does not match"):
        check_package(package, FilingType.NOD, manifest=manifest)


def test_a_default_run_reports_the_filing_checks_it_did_not_run(tmp_path: Path) -> None:
    """The default run omits every filing-specific rule; the report has to say so.

    Six of the twenty rules that apply to an NOE filing are experimental, and two of them
    can fail. A default run over a package missing its primary form therefore returns exit
    code 0, so the report is the only place the omission can be disclosed.
    """

    package, manifest = _package(tmp_path)

    report, exit_code = check_package(package, FilingType.NOE, manifest=manifest)

    assert exit_code == 0
    assert not any(finding.status is FindingStatus.FAILURE for finding in report.findings)
    assert [skipped.rule_id for skipped in report.not_run] == [
        "NOE-001",
        "NOE-002",
        "NOE-003",
        "NOE-M001",
        "NOE-M002",
        "NOE-M003",
    ]
    assert {skipped.reason for skipped in report.not_run} == {SkipReason.EXPERIMENTAL_NOT_INCLUDED}
    assert all("--include-experimental" in skipped.detail for skipped in report.not_run)


def test_deselected_rules_are_reported_in_catalog_order(tmp_path: Path) -> None:
    package, manifest = _package(tmp_path)

    report, exit_code = check_package(
        package,
        FilingType.NOE,
        manifest=manifest,
        include_experimental=True,
        exclude_rule_ids={"NOE-001", "CORE-001"},
    )

    assert exit_code == 0
    assert [skipped.rule_id for skipped in report.not_run] == ["CORE-001", "NOE-001"]
    assert {skipped.reason for skipped in report.not_run} == {SkipReason.EXCLUDED_BY_REQUEST}
    checklist = render_checklist(report)
    assert "Checks that did not run" in checklist
    assert "CORE-001" in checklist


def test_a_complete_run_states_that_nothing_was_skipped(tmp_path: Path) -> None:
    package, manifest = _package(tmp_path)

    report, _ = check_package(package, FilingType.NOE, manifest=manifest, include_experimental=True)

    assert report.not_run == []
    for rendered in (render_console(report), render_checklist(report), render_html(report)):
        assert "Every check that applies to this filing type ran." in rendered


def test_html_report_labels_the_kind_of_authority_behind_each_citation(tmp_path: Path) -> None:
    """Issue #38: a self-cited rule must not render the same "Source" link as official guidance.

    FILE-004 and FILE-005 cite this project's own reasoning because no official guidance
    states their thresholds. The HTML report has to say so next to the link, and the link
    has to point at the page that explains the threshold rather than a repository root.
    """

    package, manifest = _package(tmp_path)
    (package / "bad name!.pdf").write_bytes((package / "NOE_example.pdf").read_bytes())

    report, _ = check_package(package, FilingType.NOE, manifest=manifest)
    html = render_html(report)

    file_005 = next(finding for finding in report.findings if finding.rule_id == "FILE-005")
    assert file_005.source is not None
    assert file_005.source.kind is SourceKind.PROJECT_ADVISORY
    assert file_005.source.url.endswith("rule-source-review-2026-07-27-addendum.md")
    assert "Project advisory rule" in html
    assert "Not an official source" in html
    assert "Official source" in html
    assert ">Source<" not in html
    assert '"kind": "project_advisory"' in render_json(report)
