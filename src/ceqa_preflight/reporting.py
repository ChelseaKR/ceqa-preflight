"""Small, accessible-by-default text and JSON report renderers."""

from __future__ import annotations

import json
from collections import Counter

from jinja2 import Environment, PackageLoader, select_autoescape

from ceqa_preflight.models import (
    Finding,
    FindingStatus,
    InspectionReport,
    SkippedCheck,
    SourceKind,
)

_TEMPLATES = Environment(
    loader=PackageLoader("ceqa_preflight", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html", "j2"), default_for_string=True),
)


def render_json(report: InspectionReport) -> str:
    """Return stable, indented JSON for a report without writing to disk."""

    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def _render_finding(finding: Finding) -> str:
    location = f" ({finding.document})" if finding.document else ""
    return f"[{finding.status.value.upper()}] {finding.rule_id}{location}: {finding.message}"


def _render_skipped(skipped: SkippedCheck) -> str:
    return f"[NOT RUN] {skipped.rule_id} ({skipped.title}): {skipped.detail}"


def summarize_counts(report: InspectionReport) -> dict[str, int]:
    """Return finding counts by status, including manual-review and not-run items."""

    counts = Counter(finding.status.value for finding in report.findings)
    return {
        "failure": counts.get(FindingStatus.FAILURE.value, 0),
        "warning": counts.get(FindingStatus.WARNING.value, 0),
        "pass": counts.get(FindingStatus.PASS.value, 0),
        "manual": len(report.manual_review),
        "not_run": len(report.not_run),
    }


ALL_CHECKS_RAN = "Every check that applies to this filing type ran."


def _scope_line(report: InspectionReport) -> str:
    """State the run's coverage so a clean result can never be mistaken for a full one."""

    if not report.not_run:
        return ALL_CHECKS_RAN
    return (
        f"Scope: {len(report.not_run)} applicable check(s) did not run. This report makes no "
        "statement about what they cover."
    )


def _summary_line(report: InspectionReport) -> str:
    counts = summarize_counts(report)
    return (
        f"Summary: {counts['failure']} failure(s), {counts['warning']} warning(s), "
        f"{counts['pass']} passed check(s), {counts['manual']} manual-review item(s), "
        f"{counts['not_run']} check(s) not run."
    )


def render_console(report: InspectionReport) -> str:
    """Return plain text that remains useful with a terminal screen reader."""

    lines = [
        "CEQA Preflight advisory report",
        report.disclaimer,
        "",
        _summary_line(report),
        _scope_line(report),
        "",
    ]
    lines.extend(_render_finding(finding) for finding in report.findings)
    if report.manual_review:
        lines.extend(["", "Manual review"])
        lines.extend(_render_finding(finding) for finding in report.manual_review)
    if report.not_run:
        lines.extend(["", "Checks that did not run"])
        lines.extend(_render_skipped(skipped) for skipped in report.not_run)
    return "\n".join(lines) + "\n"


# A citation link is the one affordance a reader has for checking a rule's authority, so
# its label must say what kind of authority sits behind it (issue #38).
SOURCE_LABELS = {
    SourceKind.OFFICIAL: "Official source",
    SourceKind.TECHNICAL_REFERENCE: "Technical reference",
    SourceKind.PROJECT_ADVISORY: "Project advisory rule",
}
SOURCE_NOTES = {
    SourceKind.OFFICIAL: "",
    SourceKind.TECHNICAL_REFERENCE: "Not CEQA guidance; a general technical reference.",
    SourceKind.PROJECT_ADVISORY: (
        "Not an official source: no official guidance states this threshold. The link "
        "explains the project's reasoning."
    ),
}


def render_html(report: InspectionReport) -> str:
    """Render a self-contained, semantic HTML report without JavaScript."""

    return _TEMPLATES.get_template("report.html.j2").render(
        report=report,
        counts=summarize_counts(report),
        source_labels=SOURCE_LABELS,
        source_notes=SOURCE_NOTES,
    )


def _not_run_checklist_lines(report: InspectionReport) -> list[str]:
    """Make every skipped check something a signer has to acknowledge, not discover."""

    if not report.not_run:
        return []  # the scope line above already states that every applicable check ran
    lines = ["", "Checks that did not run — this checklist does not cover them"]
    for skipped in report.not_run:
        lines.append(f"[ ] {skipped.rule_id} ({skipped.title}) was not run.")
        lines.append(f"    {skipped.detail}")
    return lines


def render_checklist(report: InspectionReport) -> str:
    """Render a printable pre-submission sign-off checklist from a report."""

    lines = [
        "CEQA Preflight pre-submission checklist",
        report.disclaimer,
        "",
        f"Filing type: {report.filing_type.value}",
        f"Package fingerprint: {report.input_fingerprint}",
        f"Generated at: {report.generated_at.isoformat()}",
        "",
        _summary_line(report),
        _scope_line(report),
        *_not_run_checklist_lines(report),
    ]
    unresolved = [
        finding
        for finding in report.findings
        if finding.status in {FindingStatus.FAILURE, FindingStatus.WARNING}
    ]
    if unresolved:
        lines.extend(["", "Resolve before submission"])
        for finding in unresolved:
            lines.append(f"[ ] {_render_finding(finding)}")
            lines.append(f"    Remediation: {finding.remediation}")
    lines.extend(["", "Manual review sign-off"])
    if report.manual_review:
        for finding in report.manual_review:
            lines.append(f"[ ] {finding.rule_id}: {finding.message}")
            lines.append(f"    Remediation: {finding.remediation}")
            lines.append("    Reviewed by: ______________________  Date: ____________")
    else:
        lines.append("No manual-review items were generated.")
    return "\n".join(lines) + "\n"
