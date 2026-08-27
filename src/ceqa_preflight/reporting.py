"""Small, accessible-by-default text and JSON report renderers."""

from __future__ import annotations

import json
from collections import Counter

from jinja2 import Environment, PackageLoader, select_autoescape

from ceqa_preflight.i18n import active_locale, ngettext
from ceqa_preflight.i18n import gettext as _
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
# Exposed as globals rather than through `install_gettext_callables`, which is added to the
# Environment dynamically by `jinja2.ext.i18n` and so is invisible to a strict type check.
# Both callables read the active locale when the template calls them, so one Environment
# serves every run instead of a per-locale one that could be built once and then go stale.
_TEMPLATES.globals["_"] = _
_TEMPLATES.globals["ngettext"] = ngettext


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


def all_checks_ran() -> str:
    """The one sentence a clean, complete run is allowed to end on."""

    return _("Every check that applies to this filing type ran.")


def _scope_line(report: InspectionReport) -> str:
    """State the run's coverage so a clean result can never be mistaken for a full one."""

    if not report.not_run:
        return all_checks_ran()
    counted = _(
        "{count} applicable check(s) did not run. This report makes no statement "
        "about what they cover."
    ).format(count=len(report.not_run))
    return f"{_('Scope')}: {counted}"


def _summary_line(report: InspectionReport) -> str:
    counts = summarize_counts(report)
    counted = _(
        "{failure} failure(s), {warning} warning(s), {passed} passed check(s), "
        "{manual} manual-review item(s), {not_run} check(s) not run."
    ).format(
        failure=counts["failure"],
        warning=counts["warning"],
        passed=counts["pass"],
        manual=counts["manual"],
        not_run=counts["not_run"],
    )
    return f"{_('Summary')}: {counted}"


def render_console(report: InspectionReport) -> str:
    """Return plain text that remains useful with a terminal screen reader."""

    lines = [
        _("CEQA Preflight advisory report"),
        report.disclaimer,
        "",
        _summary_line(report),
        _scope_line(report),
        "",
    ]
    lines.extend(_render_finding(finding) for finding in report.findings)
    if report.manual_review:
        lines.extend(["", _("Manual review")])
        lines.extend(_render_finding(finding) for finding in report.manual_review)
    if report.not_run:
        lines.extend(["", _("Checks that did not run")])
        lines.extend(_render_skipped(skipped) for skipped in report.not_run)
    return "\n".join(lines) + "\n"


# A citation link is the one affordance a reader has for checking a rule's authority, so
# its label must say what kind of authority sits behind it (issue #38).
def source_labels() -> dict[SourceKind, str]:
    """Say what kind of authority sits behind each citation link, in the active locale."""

    return {
        SourceKind.OFFICIAL: _("Official source"),
        SourceKind.TECHNICAL_REFERENCE: _("Technical reference"),
        SourceKind.PROJECT_ADVISORY: _("Project advisory rule"),
    }


def source_notes() -> dict[SourceKind, str]:
    """Qualify the two kinds of citation that are not official CEQA guidance."""

    return {
        SourceKind.OFFICIAL: "",
        SourceKind.TECHNICAL_REFERENCE: _("Not CEQA guidance; a general technical reference."),
        SourceKind.PROJECT_ADVISORY: _(
            "Not an official source: no official guidance states this threshold. The link "
            "explains the project's reasoning."
        ),
    }


def render_html(report: InspectionReport) -> str:
    """Render a self-contained, semantic HTML report without JavaScript."""

    return _TEMPLATES.get_template("report.html.j2").render(
        report=report,
        counts=summarize_counts(report),
        source_labels=source_labels(),
        source_notes=source_notes(),
        lang=active_locale(),
    )


def _not_run_checklist_lines(report: InspectionReport) -> list[str]:
    """Make every skipped check something a signer has to acknowledge, not discover."""

    if not report.not_run:
        return []  # the scope line above already states that every applicable check ran
    lines = ["", _("Checks that did not run — this checklist does not cover them")]
    for skipped in report.not_run:
        lines.append(
            "[ ] "
            + _("{rule_id} ({title}) was not run.").format(
                rule_id=skipped.rule_id, title=skipped.title
            )
        )
        lines.append(f"    {skipped.detail}")
    return lines


def render_checklist(report: InspectionReport) -> str:
    """Render a printable pre-submission sign-off checklist from a report."""

    lines = [
        _("CEQA Preflight pre-submission checklist"),
        report.disclaimer,
        "",
        _("Filing type: {value}").format(value=report.filing_type.value),
        _("Package fingerprint: {value}").format(value=report.input_fingerprint),
        _("Generated at: {value}").format(value=report.generated_at.isoformat()),
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
        lines.extend(["", _("Resolve before submission")])
        for finding in unresolved:
            lines.append(f"[ ] {_render_finding(finding)}")
            lines.append("    " + _("Remediation: {value}").format(value=finding.remediation))
    lines.extend(["", _("Manual review sign-off")])
    if report.manual_review:
        for finding in report.manual_review:
            lines.append(f"[ ] {finding.rule_id}: {finding.message}")
            lines.append("    " + _("Remediation: {value}").format(value=finding.remediation))
            lines.append("    " + _("Reviewed by: ______________________  Date: ____________"))
    else:
        lines.append(_("No manual-review items were generated."))
    return "\n".join(lines) + "\n"
