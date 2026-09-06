"""Small, accessible-by-default text and JSON report renderers."""

from __future__ import annotations

import json
from collections import Counter

# Serialization only: this module builds a JUnit document and never parses XML, so the
# untrusted-input attack B405 warns about has no input here. `defusedxml` hardens the
# parsers, which this module does not use, and adds a dependency to the shipped wheel.
from xml.etree import ElementTree  # nosec B405

from jinja2 import Environment, PackageLoader, select_autoescape

from ceqa_preflight.diffing import (
    DiffReport,
    FindingChange,
    FindingDelta,
    ProvenanceMismatch,
    SkipChange,
)
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


# --- comparison reports ---------------------------------------------------------------
# A diff renders through the same locale seam as a report, and to the same three formats.
# The JSON is the model's own dump, so every machine-readable value stays a stable
# identifier; only the prose these functions build is localizable.


def _diff_location(delta: FindingDelta) -> str:
    parts = [part for part in (delta.document, delta.field) if part]
    return f" ({', '.join(parts)})" if parts else ""


def _finding_change_labels() -> dict[FindingChange, str]:
    return {
        FindingChange.ADDED: _("NEW"),
        FindingChange.REMOVED: _("GONE"),
        FindingChange.CHANGED: _("CHANGED"),
        FindingChange.UNCHANGED: _("SAME"),
        FindingChange.NOT_COMPARABLE: _("NOT COMPARABLE"),
    }


def _skip_change_labels() -> dict[SkipChange, str]:
    return {
        SkipChange.STILL_NOT_RUN: _("still did not run"),
        SkipChange.REASON_CHANGED: _("did not run in either report, for a different reason"),
        SkipChange.NOW_RAN: _("did not run before; it ran this time"),
        SkipChange.NOW_NOT_RUN: _("ran before; it did not run this time"),
        SkipChange.NOT_COMPARABLE: _(
            "did not run in one report and is absent from the other, so these reports "
            "cannot be compared on it"
        ),
    }


def _attribute_labels() -> dict[str, str]:
    return {
        "status": _("status"),
        "message": _("message"),
        "page": _("page"),
        "remediation": _("remediation"),
        "confidence": _("confidence"),
        "rule_version": _("rule version"),
        "title": _("title"),
    }


def _mismatch_labels() -> dict[ProvenanceMismatch, str]:
    return {
        ProvenanceMismatch.REPORT_SCHEMA_VERSION: _(
            "The two reports use different report schema versions ({before} and {after})."
        ),
        ProvenanceMismatch.TOOL_VERSION: _(
            "The two reports were produced by different tool versions ({before} and {after})."
        ),
        ProvenanceMismatch.RULESET_VERSION: _(
            "The two reports were produced against different rulesets ({before} and "
            "{after}). A check that no longer appears may have left the ruleset rather "
            "than been resolved."
        ),
        ProvenanceMismatch.FILING_TYPE: _(
            "The two reports describe different filing types ({before} and {after})."
        ),
        ProvenanceMismatch.INPUT_FINGERPRINT: _(
            "The two reports describe different package contents ({before} and {after})."
        ),
    }


def _mismatch_values(diff: DiffReport, kind: ProvenanceMismatch) -> tuple[str, str]:
    before = getattr(diff.before, kind.value)
    after = getattr(diff.after, kind.value)
    return (str(getattr(before, "value", before)), str(getattr(after, "value", after)))


def diff_warning_lines(diff: DiffReport) -> list[str]:
    """State every way the two reports fail to describe the same thing, before any delta."""

    labels = _mismatch_labels()
    return [
        labels[kind].format(before=values[0], after=values[1])
        for kind in diff.mismatches
        for values in [_mismatch_values(diff, kind)]
    ]


def _diff_status_pair(delta: FindingDelta) -> str:
    before = delta.before.status.value if delta.before else "-"
    after = delta.after.status.value if delta.after else "-"
    return f"{before} -> {after}"


def _render_finding_delta(delta: FindingDelta, labels: dict[FindingChange, str]) -> str:
    head = f"[{labels[delta.change]}] {delta.rule_id}{_diff_location(delta)}"
    if delta.change is FindingChange.NOT_COMPARABLE:
        return (
            head
            + ": "
            + _(
                "{before} finding(s) before and {after} after share this rule, document and "
                "field, so no pairing between them is knowable."
            ).format(before=delta.before_count, after=delta.after_count)
        )
    if delta.change is FindingChange.ADDED and delta.after is not None:
        return f"{head}: {delta.after.status.value}: {delta.after.message}"
    if delta.change is FindingChange.REMOVED and delta.before is not None:
        return f"{head}: {_('was')} {delta.before.status.value}: {delta.before.message}"
    if delta.change is FindingChange.CHANGED:
        attribute_labels = _attribute_labels()
        changed = ", ".join(attribute_labels[name] for name in delta.changed_attributes)
        return f"{head}: {_diff_status_pair(delta)} ({changed})"
    return f"{head}: {_diff_status_pair(delta)}"


def diff_counts(diff: DiffReport) -> dict[str, int]:
    """Counts by change kind, plus regressions and incomparable pairings."""

    kinds = Counter(delta.change.value for delta in diff.findings)
    return {
        "added": kinds.get(FindingChange.ADDED.value, 0),
        "removed": kinds.get(FindingChange.REMOVED.value, 0),
        "changed": kinds.get(FindingChange.CHANGED.value, 0),
        "unchanged": kinds.get(FindingChange.UNCHANGED.value, 0),
        "not_comparable": kinds.get(FindingChange.NOT_COMPARABLE.value, 0),
        "regressions": len(diff.regressions),
    }


def render_diff_json(diff: DiffReport) -> str:
    """Return stable, indented JSON for a comparison without writing to disk."""

    return json.dumps(diff.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def diff_summary_line(diff: DiffReport) -> str:
    counts = diff_counts(diff)
    counted = _(
        "{added} new, {removed} no longer reported, {changed} changed, {unchanged} "
        "unchanged, {not_comparable} not comparable, {regressions} regression(s)."
    ).format(
        added=counts["added"],
        removed=counts["removed"],
        changed=counts["changed"],
        unchanged=counts["unchanged"],
        not_comparable=counts["not_comparable"],
        regressions=counts["regressions"],
    )
    return f"{_('Summary')}: {counted}"


def diff_no_change_line(diff: DiffReport) -> str:
    """What an unchanged comparison says, so an empty screen never stands for a result."""

    return _(
        "No finding and no skipped check moved between these two reports of package "
        "fingerprint {fingerprint}."
    ).format(fingerprint=diff.after.input_fingerprint)


def render_diff_console(diff: DiffReport) -> str:
    """Return plain text that remains useful with a terminal screen reader."""

    lines = [_("CEQA Preflight report comparison"), diff.disclaimer, ""]
    warnings = diff_warning_lines(diff)
    if warnings:
        lines.append(_("Before any comparison"))
        lines.extend(warnings)
        lines.append("")
    lines.append(diff_summary_line(diff))
    if diff.is_unchanged:
        lines.extend(["", diff_no_change_line(diff)])
        return "\n".join(lines) + "\n"
    labels = _finding_change_labels()
    moved = diff.moved
    if moved:
        lines.extend(["", _("Findings that moved")])
        lines.extend(_render_finding_delta(delta, labels) for delta in moved)
    skip_labels = _skip_change_labels()
    skips = [delta for delta in diff.not_run if delta.change is not SkipChange.STILL_NOT_RUN]
    if skips:
        lines.extend(["", _("Checks that did not run")])
        for delta in skips:
            lines.append(f"{delta.rule_id} ({delta.title}): {skip_labels[delta.change]}")
    return "\n".join(lines) + "\n"


def render_diff_html(diff: DiffReport) -> str:
    """Render a self-contained, semantic HTML comparison without JavaScript."""

    return _TEMPLATES.get_template("diff.html.j2").render(
        diff=diff,
        counts=diff_counts(diff),
        warnings=diff_warning_lines(diff),
        summary=diff_summary_line(diff),
        no_change=diff_no_change_line(diff),
        change_labels=_finding_change_labels(),
        skip_labels=_skip_change_labels(),
        attribute_labels=_attribute_labels(),
        location=_diff_location,
        status_pair=_diff_status_pair,
        lang=active_locale(),
    )


# ── Machine-readable CI formats (SARIF 2.1.0, JUnit XML) ──────────────────────
#
# Deliberately NOT localized. Both are consumed by tooling — GitHub code
# scanning, a JUnit summary plugin — not read as prose, and their element names
# and level vocabularies are fixed by their specifications. `finding.message`
# and the other report fields are already rendered in the active locale by the
# time they arrive here, so a Spanish run produces a Spanish message inside an
# English envelope, which is what both formats expect.

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/"
    "sarif-2.1/schema/sarif-schema-2.1.0.json"
)
INFORMATION_URI = "https://github.com/ChelseaKR/ceqa-preflight"

# A status maps to a SARIF level. `pass` is `none`, and carries `kind: "pass"`
# so a clean run is a stated result rather than an empty file: an empty SARIF
# and a SARIF saying every rule passed look identical to a reader otherwise.
_SARIF_LEVELS: dict[FindingStatus, str] = {
    FindingStatus.FAILURE: "error",
    FindingStatus.WARNING: "warning",
    FindingStatus.MANUAL: "note",
    FindingStatus.PASS: "none",
}


def _sarif_rule(finding: Finding) -> dict[str, object]:
    properties: dict[str, object] = {"ruleVersion": finding.rule_version}
    rule: dict[str, object] = {
        "id": finding.rule_id,
        "name": finding.rule_id,
        "shortDescription": {"text": finding.title},
        "properties": properties,
    }
    if finding.source is not None:
        rule["helpUri"] = finding.source.url
        properties["kind"] = finding.source.kind.value
        properties["sourceTitle"] = finding.source.title
    return rule


def _sarif_result(finding: Finding) -> dict[str, object]:
    properties: dict[str, object] = {
        "status": finding.status.value,
        "confidence": finding.confidence.value,
        "remediation": finding.remediation,
    }
    result: dict[str, object] = {
        "ruleId": finding.rule_id,
        "level": _SARIF_LEVELS[finding.status],
        "message": {"text": finding.message},
        "properties": properties,
    }
    if finding.status is FindingStatus.PASS:
        result["kind"] = "pass"
    if finding.document is not None:
        location: dict[str, object] = {"artifactLocation": {"uri": finding.document}}
        if finding.page is not None:
            # A page is not a line. SARIF regions are text ranges, so the page
            # goes in properties rather than being coerced into a startLine that
            # would point a reader at the wrong place in the file.
            properties["page"] = finding.page
        result["locations"] = [{"physicalLocation": location}]
    return result


def _sarif_notification(skipped: SkippedCheck) -> dict[str, object]:
    """A rule that did not run, as a SARIF notification.

    Dropping these would make a report of what ran indistinguishable from a
    report about the whole package — the same reason `SkippedCheck` exists.
    """

    return {
        "descriptor": {"id": skipped.rule_id},
        "level": "note",
        "message": {"text": f"{skipped.title}: {skipped.detail}"},
        "properties": {
            "reason": skipped.reason.value,
            "ruleVersion": skipped.rule_version,
        },
    }


def _sarif_error_notification(finding: Finding) -> dict[str, object]:
    """A rule whose check threw, as an error-level SARIF notification.

    SARIF puts "the tool could not analyse this" in `toolExecutionNotifications`,
    not in `results`, which is where a *finding* goes. This one is both: the
    warning stays in `results` so nothing disappears, and the notification is
    what makes `executionSuccessful: false` diagnosable rather than bare.
    """

    return {
        "descriptor": {"id": finding.rule_id},
        "associatedRule": {"id": finding.rule_id},
        "level": "error",
        "message": {"text": finding.message},
        "properties": {
            "reason": "internal_rule_error",
            "ruleVersion": finding.rule_version,
        },
    }


def render_sarif(report: InspectionReport) -> str:
    """Render a report as SARIF 2.1.0 for code scanning.

    `executionSuccessful` is read off the report rather than asserted. A check
    that threw evaluated nothing, which is the same thing `not_run` records and
    the same reason both are disclosed here: a run that could not complete every
    rule must not be indistinguishable from one that did.
    """

    scored = list(report.findings) + list(report.manual_review)
    incomplete = [finding for finding in scored if not finding.check_completed]
    rules: dict[str, dict[str, object]] = {}
    for finding in scored:
        rules.setdefault(finding.rule_id, _sarif_rule(finding))
    notifications = [_sarif_notification(skipped) for skipped in report.not_run]
    notifications.extend(_sarif_error_notification(finding) for finding in incomplete)
    document = {
        "$schema": SARIF_SCHEMA,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "CEQA Preflight",
                        "version": report.tool_version,
                        "semanticVersion": report.tool_version,
                        "informationUri": INFORMATION_URI,
                        "rules": [rules[key] for key in sorted(rules)],
                        "notifications": [
                            {"id": skipped.rule_id, "shortDescription": {"text": skipped.title}}
                            for skipped in report.not_run
                        ]
                        + [
                            {"id": finding.rule_id, "shortDescription": {"text": finding.title}}
                            for finding in incomplete
                        ],
                    }
                },
                "invocations": [
                    {
                        "executionSuccessful": not incomplete,
                        "toolExecutionNotifications": notifications,
                    }
                ],
                "properties": {
                    "rulesetVersion": report.ruleset_version,
                    "filingType": report.filing_type.value,
                    "inputFingerprint": report.input_fingerprint,
                    "reportSchemaVersion": report.report_schema_version,
                    "generatedAt": report.generated_at.isoformat(),
                    "disclaimer": report.disclaimer,
                },
                "results": [_sarif_result(finding) for finding in scored],
            }
        ],
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def _junit_text(finding: Finding) -> str:
    location = f" ({finding.document})" if finding.document else ""
    return f"{finding.status.value.upper()} {finding.rule_id}{location}: {finding.message}"


def render_junit(report: InspectionReport) -> str:
    """Render a report as JUnit XML for a CI job summary.

    ``<skipped>`` is reserved for `not_run`, and nothing else uses it: JUnit
    readers total skips as "did not execute", so mapping a manual-review item
    or a warning onto it would report a check that ran as one that did not.
    A warning and a manual-review item are passing test cases carrying their
    text in ``<system-out>``; only a failure is a ``<failure>``.

    ``<error>`` is reserved, symmetrically, for a check that threw. JUnit already
    separates "the assertion did not hold" from "the test could not run", and a
    check the engine had to raise its own finding for is the second: it concluded
    nothing about the package. Rendered as a ``<system-out>`` warning it would be
    a *passing* test case, and the suite's ``errors`` count -- the one attribute
    that exists to carry exactly this -- would stay at the literal zero it used
    to be, on a run the tool itself exits 2 for.
    """

    scored = list(report.findings) + list(report.manual_review)
    suite = ElementTree.Element(
        "testsuite",
        {
            "name": "ceqa-preflight",
            "tests": str(len(scored) + len(report.not_run)),
            "failures": str(sum(1 for f in report.findings if f.status is FindingStatus.FAILURE)),
            "errors": str(sum(1 for f in scored if not f.check_completed)),
            "skipped": str(len(report.not_run)),
            "timestamp": report.generated_at.isoformat(),
        },
    )
    classname = f"ceqa-preflight.{report.filing_type.value}"
    for finding in scored:
        case = ElementTree.SubElement(
            suite,
            "testcase",
            {"name": f"{finding.rule_id}: {finding.title}", "classname": classname},
        )
        if not finding.check_completed:
            error = ElementTree.SubElement(
                case, "error", {"message": finding.message, "type": "internal_rule_error"}
            )
            error.text = f"{_junit_text(finding)}\n{finding.remediation}"
        elif finding.status is FindingStatus.FAILURE:
            failure = ElementTree.SubElement(
                case, "failure", {"message": finding.message, "type": finding.status.value}
            )
            failure.text = f"{_junit_text(finding)}\n{finding.remediation}"
        elif finding.status is not FindingStatus.PASS:
            ElementTree.SubElement(case, "system-out").text = _junit_text(finding)
    for skipped in report.not_run:
        case = ElementTree.SubElement(
            suite,
            "testcase",
            {"name": f"{skipped.rule_id}: {skipped.title}", "classname": classname},
        )
        ElementTree.SubElement(
            case, "skipped", {"message": f"{skipped.reason.value}: {skipped.detail}"}
        )
    suites = ElementTree.Element("testsuites", dict(suite.attrib))
    suites.append(suite)
    ElementTree.indent(suites, space="  ")
    return ElementTree.tostring(suites, encoding="unicode", xml_declaration=True) + "\n"
