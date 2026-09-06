"""SARIF 2.1.0 and JUnit XML renderings of an `InspectionReport`.

Both are pure renderings of a report that has already been produced, so these
tests build reports directly rather than running a check. The point of interest
in both formats is the same one the report model exists for: a run that did not
execute every rule must not render as a clean bill of health. SARIF carries the
skips as notifications; JUnit carries them as `<skipped>`, and reserves that
element for them alone.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from xml.etree import ElementTree  # our own output

import pytest

from ceqa_preflight.models import (
    Confidence,
    FilingType,
    Finding,
    FindingStatus,
    InspectionReport,
    SkippedCheck,
    SkipReason,
    SourceCitation,
    SourceKind,
)
from ceqa_preflight.reporting import SARIF_VERSION, render_junit, render_sarif

_SOURCE = SourceCitation(
    title="LCI CEQA Submit common mistakes",
    url="https://lci.ca.gov/sch/docs/example.pdf",
    kind=SourceKind.OFFICIAL,
)


def _finding(
    rule_id: str = "PDF-001",
    *,
    status: FindingStatus = FindingStatus.FAILURE,
    document: str | None = "notice.pdf",
    page: int | None = None,
    source: SourceCitation | None = _SOURCE,
) -> Finding:
    return Finding(
        rule_id=rule_id,
        rule_version="1.0.0",
        status=status,
        title="Text layer present",
        message="The document has no text layer.",
        document=document,
        page=page,
        remediation="Re-export the PDF with searchable text.",
        source=source,
        confidence=Confidence.HIGH,
    )


def _skipped(rule_id: str = "PDF-009") -> SkippedCheck:
    return SkippedCheck(
        rule_id=rule_id,
        rule_version="1.0.0",
        title="Experimental filing rule",
        reason=SkipReason.EXPERIMENTAL_NOT_INCLUDED,
        detail="It was not selected for this run.",
    )


def _report(
    findings: list[Finding] | None = None,
    *,
    manual_review: list[Finding] | None = None,
    not_run: list[SkippedCheck] | None = None,
) -> InspectionReport:
    return InspectionReport(
        tool_version="0.1.0",
        ruleset_version="1.2.0",
        generated_at=datetime(2026, 9, 1, tzinfo=UTC),
        input_fingerprint="a" * 64,
        filing_type=FilingType.NOE,
        findings=findings or [],
        manual_review=manual_review or [],
        not_run=not_run or [],
        disclaimer="Advisory only.",
    )


def _sarif(report: InspectionReport) -> dict:
    return json.loads(render_sarif(report))


def _run(report: InspectionReport) -> dict:
    return _sarif(report)["runs"][0]


# --- SARIF ----------------------------------------------------------------------------


class TestSarifStructure:
    def test_document_declares_the_version_and_a_single_run(self) -> None:
        document = _sarif(_report([_finding()]))
        assert document["version"] == SARIF_VERSION == "2.1.0"
        assert document["$schema"].endswith("sarif-schema-2.1.0.json")
        assert len(document["runs"]) == 1

    def test_every_result_rule_id_is_declared_as_a_rule(self) -> None:
        report = _report(
            [_finding("PDF-001"), _finding("FILE-002", status=FindingStatus.WARNING)],
            manual_review=[_finding("MAN-001", status=FindingStatus.MANUAL)],
        )
        run = _run(report)

        declared = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
        used = {result["ruleId"] for result in run["results"]}

        assert used == declared == {"PDF-001", "FILE-002", "MAN-001"}

    def test_a_rules_source_becomes_its_help_uri_and_kind(self) -> None:
        rule = _run(_report([_finding()]))["tool"]["driver"]["rules"][0]
        assert rule["helpUri"] == "https://lci.ca.gov/sch/docs/example.pdf"
        assert rule["properties"]["kind"] == "official"

    def test_a_rule_with_no_source_carries_no_help_uri(self) -> None:
        rule = _run(_report([_finding(source=None)]))["tool"]["driver"]["rules"][0]
        assert "helpUri" not in rule
        assert "kind" not in rule["properties"]

    @pytest.mark.parametrize(
        ("status", "level"),
        [
            (FindingStatus.FAILURE, "error"),
            (FindingStatus.WARNING, "warning"),
            (FindingStatus.MANUAL, "note"),
            (FindingStatus.PASS, "none"),
        ],
    )
    def test_each_status_maps_to_its_documented_level(
        self, status: FindingStatus, level: str
    ) -> None:
        result = _run(_report([_finding(status=status)]))["results"][0]
        assert result["level"] == level
        assert result["properties"]["status"] == status.value

    def test_a_document_becomes_a_location_and_a_page_stays_a_property(self) -> None:
        result = _run(_report([_finding(page=4)]))["results"][0]
        location = result["locations"][0]["physicalLocation"]
        assert location["artifactLocation"]["uri"] == "notice.pdf"
        # A page is not a line; coercing it into startLine would point a reader
        # at the wrong place in the file.
        assert "region" not in location
        assert result["properties"]["page"] == 4

    def test_a_package_level_finding_has_no_location_rather_than_a_made_up_one(self) -> None:
        result = _run(_report([_finding(document=None)]))["results"][0]
        assert "locations" not in result

    def test_the_run_carries_the_reports_own_provenance(self) -> None:
        properties = _run(_report([_finding()]))["properties"]
        assert properties["rulesetVersion"] == "1.2.0"
        assert properties["inputFingerprint"] == "a" * 64
        assert properties["filingType"] == "NOE"
        assert properties["disclaimer"] == "Advisory only."


class TestSarifNeverHidesWhatDidNotRun:
    def test_every_not_run_check_becomes_a_notification(self) -> None:
        report = _report([_finding()], not_run=[_skipped("PDF-009"), _skipped("FILE-004")])
        run = _run(report)

        notifications = run["invocations"][0]["toolExecutionNotifications"]
        assert {n["descriptor"]["id"] for n in notifications} == {"PDF-009", "FILE-004"}
        assert {d["id"] for d in run["tool"]["driver"]["notifications"]} == {
            "PDF-009",
            "FILE-004",
        }

    def test_a_notification_names_why_the_rule_did_not_run(self) -> None:
        notification = _run(_report(not_run=[_skipped()]))["invocations"][0][
            "toolExecutionNotifications"
        ][0]
        assert notification["properties"]["reason"] == "experimental_not_included"
        assert "It was not selected for this run." in notification["message"]["text"]

    def test_a_skipped_rule_is_not_smuggled_in_as_a_passing_result(self) -> None:
        """A skip is not a pass. If `not_run` leaked into `results` as a passing
        finding, a code-scanning reader would count a rule that never executed
        among the ones that cleared."""

        run = _run(_report([_finding()], not_run=[_skipped("PDF-009")]))
        assert {result["ruleId"] for result in run["results"]} == {"PDF-001"}

    def test_a_clean_run_still_states_its_passes_rather_than_rendering_empty(self) -> None:
        """An empty `results` array and "every rule passed" are indistinguishable
        to a reader, so a pass is rendered as a result with `kind: "pass"`."""

        run = _run(_report([_finding(status=FindingStatus.PASS)]))
        assert run["results"][0]["kind"] == "pass"
        assert run["results"][0]["level"] == "none"


# --- JUnit ----------------------------------------------------------------------------


def _junit(report: InspectionReport) -> ElementTree.Element:
    return ElementTree.fromstring(render_junit(report))  # noqa: S314  # our own output


class TestJunit:
    def test_a_failure_is_the_only_status_that_becomes_a_failure_element(self) -> None:
        report = _report(
            [
                _finding("PDF-001", status=FindingStatus.FAILURE),
                _finding("PDF-002", status=FindingStatus.WARNING),
                _finding("PDF-003", status=FindingStatus.PASS),
            ],
            manual_review=[_finding("MAN-001", status=FindingStatus.MANUAL)],
        )
        suite = _junit(report).find("testsuite")
        assert suite is not None

        failing = [case.get("name") for case in suite if case.find("failure") is not None]
        assert failing == ["PDF-001: Text layer present"]
        assert suite.get("failures") == "1"

    def test_skipped_is_reserved_for_checks_that_did_not_run(self) -> None:
        """A JUnit reader totals `<skipped>` as "did not execute". A warning or a
        manual-review item ran and produced a result, so mapping either onto
        `<skipped>` would report a check that ran as one that did not."""

        report = _report(
            [_finding("PDF-002", status=FindingStatus.WARNING)],
            manual_review=[_finding("MAN-001", status=FindingStatus.MANUAL)],
            not_run=[_skipped("PDF-009")],
        )
        suite = _junit(report).find("testsuite")
        assert suite is not None

        skipped = [case.get("name") for case in suite if case.find("skipped") is not None]
        assert skipped == ["PDF-009: Experimental filing rule"]
        assert suite.get("skipped") == "1"

    def test_a_warning_still_says_what_it_found(self) -> None:
        suite = _junit(_report([_finding(status=FindingStatus.WARNING)])).find("testsuite")
        assert suite is not None
        system_out = suite[0].find("system-out")
        assert system_out is not None and system_out.text is not None
        assert "The document has no text layer." in system_out.text

    def test_the_case_total_counts_every_rule_including_the_ones_that_did_not_run(self) -> None:
        report = _report(
            [_finding("PDF-001"), _finding("PDF-002", status=FindingStatus.PASS)],
            manual_review=[_finding("MAN-001", status=FindingStatus.MANUAL)],
            not_run=[_skipped("PDF-009")],
        )
        suite = _junit(report).find("testsuite")
        assert suite is not None
        assert suite.get("tests") == "4"
        assert len(list(suite)) == 4

    def test_the_document_is_well_formed_and_escapes_report_text(self) -> None:
        finding = _finding()
        report = _report([finding.model_copy(update={"message": 'a & b < c > "d"'})])
        rendered = render_junit(report)

        assert rendered.startswith("<?xml")
        suite = ElementTree.fromstring(rendered).find("testsuite")  # noqa: S314  # our own output
        assert suite is not None
        failure = suite[0].find("failure")
        assert failure is not None
        assert failure.get("message") == 'a & b < c > "d"'
