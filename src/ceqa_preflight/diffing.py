"""Compare two committed check reports and name every finding that moved.

A report says what was true of one package at one moment. Nothing said what changed
between two runs, so a reviewer diffing a correction cycle read two JSON files by eye or
re-read the whole HTML report. This module turns that into a command.

Three rules shape it, and all three are about not overstating what a comparison knows.

**Absence is never resolution.** A rule that did not run in one report and is absent from
the other is ``not_comparable``: the second report says nothing about it, which is not the
same as the finding having cleared. The same discipline the ``not_run`` list already
carries in :mod:`ceqa_preflight.reporting` applies to every delta computed here.

**Ambiguity is never a guess.** Findings pair on ``rule_id`` + ``document`` + ``field``,
the identity the report schema actually offers. One rule can emit several findings against
one document under that key — a page-level rule firing twice, for instance — and there is
no field that says which of them corresponds to which. Rather than pairing them in list
order and calling the result a change, a key that is not unique on either side is reported
as ``not_comparable`` and counted separately, so the reader knows the tool declined.

**Two reports of different things are not silently merged.** A differing
``tool_version``, ``ruleset_version``, ``filing_type`` or ``input_fingerprint`` is stated
before any delta: a rule that "cleared" because the ruleset dropped it, or because the
package being checked is a different package, is not a correction. The comparison still
runs — comparing across versions is a legitimate thing to want — but it is labelled.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import Field, ValidationError

from ceqa_preflight import __version__
from ceqa_preflight.i18n import gettext as _
from ceqa_preflight.models import (
    Confidence,
    FilingType,
    Finding,
    FindingStatus,
    InspectionReport,
    SkipReason,
    StrictModel,
)

# Report schema majors this comparison understands. `InspectionReport` puts no constraint
# on `report_schema_version` — unlike `PackageManifest.schema_version`, which validates its
# major — so a report announcing `2.0` loads cleanly against the 1.x model whenever its 1.x
# fields are present. Nothing downstream would notice. `load_report` therefore reads the
# declared version out of the raw text and refuses it here, before the model runs.
SUPPORTED_REPORT_SCHEMA_MAJOR = "1"

DIFF_SCHEMA_VERSION = "1.0"


class DiffError(ValueError):
    """Raised when an input cannot be read as a report this tool knows how to compare."""


class FindingChange(StrEnum):
    """What happened to one (rule, document, field) between the two reports."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    NOT_COMPARABLE = "not_comparable"


class SkipChange(StrEnum):
    """What happened to one rule's ``not_run`` entry between the two reports."""

    STILL_NOT_RUN = "still_not_run"
    REASON_CHANGED = "reason_changed"
    NOW_RAN = "now_ran"
    NOW_NOT_RUN = "now_not_run"
    NOT_COMPARABLE = "not_comparable"


class FindingSide(StrictModel):
    """One report's view of a finding, reduced to the attributes a diff compares."""

    status: FindingStatus
    rule_version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    message: str = Field(min_length=1)
    remediation: str = Field(min_length=1)
    confidence: Confidence
    page: int | None = Field(default=None, ge=1)

    @classmethod
    def of(cls, finding: Finding) -> FindingSide:
        return cls(
            status=finding.status,
            rule_version=finding.rule_version,
            title=finding.title,
            message=finding.message,
            remediation=finding.remediation,
            confidence=finding.confidence,
            page=finding.page,
        )


# Attributes compared between two paired findings, in the order they are reported. `page`
# is included because a finding that moved to another page is a different finding about the
# same rule and document, and a reviewer chasing a correction needs to see that it moved.
_COMPARED_ATTRIBUTES: tuple[str, ...] = (
    "status",
    "message",
    "page",
    "remediation",
    "confidence",
    "rule_version",
    "title",
)


class FindingDelta(StrictModel):
    """One pairing key's outcome, with both sides where they exist."""

    rule_id: str = Field(min_length=1)
    document: str | None = None
    field: str | None = None
    change: FindingChange
    before: FindingSide | None = None
    after: FindingSide | None = None
    changed_attributes: list[str] = Field(default_factory=list)
    regression: bool = False
    before_count: int = Field(default=0, ge=0)
    after_count: int = Field(default=0, ge=0)


class SkipDelta(StrictModel):
    """One rule's ``not_run`` outcome across the two reports."""

    rule_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    change: SkipChange
    before_reason: SkipReason | None = None
    after_reason: SkipReason | None = None


class ReportSide(StrictModel):
    """The provenance of one of the two reports being compared."""

    report_schema_version: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    ruleset_version: str = Field(min_length=1)
    generated_at: datetime
    input_fingerprint: str = Field(min_length=1)
    filing_type: FilingType

    @classmethod
    def of(cls, report: InspectionReport) -> ReportSide:
        return cls(
            report_schema_version=report.report_schema_version,
            tool_version=report.tool_version,
            ruleset_version=report.ruleset_version,
            generated_at=report.generated_at,
            input_fingerprint=report.input_fingerprint,
            filing_type=report.filing_type,
        )


class ProvenanceMismatch(StrEnum):
    """A way in which the two reports do not describe the same run of the same thing."""

    TOOL_VERSION = "tool_version"
    RULESET_VERSION = "ruleset_version"
    FILING_TYPE = "filing_type"
    INPUT_FINGERPRINT = "input_fingerprint"
    REPORT_SCHEMA_VERSION = "report_schema_version"


class DiffReport(StrictModel):
    """Versioned, JSON-serializable output for a comparison of two check reports."""

    diff_schema_version: str = Field(default=DIFF_SCHEMA_VERSION)
    tool_version: str = Field(min_length=1)
    generated_at: datetime
    before: ReportSide
    after: ReportSide
    mismatches: list[ProvenanceMismatch] = Field(default_factory=list)
    findings: list[FindingDelta] = Field(default_factory=list)
    not_run: list[SkipDelta] = Field(default_factory=list)
    disclaimer: str = Field(min_length=1)

    @property
    def same_package(self) -> bool:
        """Do both reports describe byte-identical input? Not "did nothing change"."""

        return ProvenanceMismatch.INPUT_FINGERPRINT not in self.mismatches

    @property
    def regressions(self) -> list[FindingDelta]:
        return [delta for delta in self.findings if delta.regression]

    @property
    def moved(self) -> list[FindingDelta]:
        """Every delta a reader needs to look at: anything but ``unchanged``."""

        return [delta for delta in self.findings if delta.change is not FindingChange.UNCHANGED]

    @property
    def unchanged(self) -> list[FindingDelta]:
        return [delta for delta in self.findings if delta.change is FindingChange.UNCHANGED]

    @property
    def not_comparable(self) -> list[FindingDelta]:
        return [delta for delta in self.findings if delta.change is FindingChange.NOT_COMPARABLE]

    @property
    def is_unchanged(self) -> bool:
        """No finding moved, no ``not_run`` entry moved, and nothing was incomparable."""

        return not self.moved and all(
            delta.change is SkipChange.STILL_NOT_RUN for delta in self.not_run
        )


def diff_disclaimer() -> str:
    """The advisory framing every comparison carries, in the active locale.

    Held to the same limit `docs/I18N.md` puts on the report disclaimer: no wording may
    imply that a cleared finding is a legal determination, because it is not one.
    """

    return _(
        "This comparison describes what two advisory technical reports say. It is not "
        "legal advice, and a finding that no longer appears has not been determined "
        "compliant."
    )


def load_report(raw: str) -> InspectionReport:
    """Parse one JSON report, refusing a schema this tool does not know.

    The declared ``report_schema_version`` is checked *before* the model runs, because
    ``InspectionReport`` does not constrain that field: a report announcing schema ``2.0``
    validates cleanly against the 1.x model as long as its 1.x fields happen to be present,
    and would then be compared as though the tool understood it. Reading the version first
    is what makes the refusal real rather than incidental — and it turns pydantic's
    field-level complaint into a sentence naming the actual reason.
    """

    declared = _declared_schema_version(raw)
    if declared is not None and declared.partition(".")[0] != SUPPORTED_REPORT_SCHEMA_MAJOR:
        raise DiffError(
            _(
                "report schema {declared} is not one this tool can compare; it "
                "understands {supported}.x"
            ).format(declared=declared, supported=SUPPORTED_REPORT_SCHEMA_MAJOR)
        )
    try:
        return InspectionReport.model_validate_json(raw)
    except ValidationError as error:
        raise DiffError(
            _("that file is not a check report this tool can read: {error}").format(error=error)
        ) from error


def _declared_schema_version(raw: str) -> str | None:
    """Best-effort read of ``report_schema_version`` from the raw text.

    ``None`` means "the file does not say", which is left to the model to reject; it never
    means "the version is fine".
    """

    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    declared = payload.get("report_schema_version")
    return declared if isinstance(declared, str) else None


_Key = tuple[str, str | None, str | None]


def _key(finding: Finding) -> _Key:
    return (finding.rule_id, finding.document, finding.field)


def _index(report: InspectionReport) -> dict[_Key, list[Finding]]:
    """Every finding in one report, including manual-review items, grouped by pairing key.

    Manual-review items are findings the engine routed to a separate list for presentation;
    they carry the same identity and the same rule, and leaving them out would report a
    ``manual`` item that became a ``failure`` as a removal plus an addition.
    """

    grouped: dict[_Key, list[Finding]] = defaultdict(list)
    for finding in [*report.findings, *report.manual_review]:
        grouped[_key(finding)].append(finding)
    return dict(grouped)


def _changed_attributes(before: Finding, after: Finding) -> list[str]:
    return [name for name in _COMPARED_ATTRIBUTES if getattr(before, name) != getattr(after, name)]


def _is_regression(before: Finding | None, after: Finding | None) -> bool:
    """A new failure, or a finding that became a failure. Nothing else is claimed.

    Deliberately narrow. "Warning became manual review" is a change a reader should see,
    and the diff shows it, but calling it a regression would put a number on a judgement
    this tool is not entitled to make.
    """

    if after is None or after.status is not FindingStatus.FAILURE:
        return False
    return before is None or before.status is not FindingStatus.FAILURE


def _finding_deltas(before: InspectionReport, after: InspectionReport) -> list[FindingDelta]:
    before_index = _index(before)
    after_index = _index(after)
    deltas: list[FindingDelta] = []
    for key in sorted(
        set(before_index) | set(after_index),
        key=lambda item: (item[0], item[1] or "", item[2] or ""),
    ):
        left = before_index.get(key, [])
        right = after_index.get(key, [])
        rule_id, document, field = key
        if len(left) > 1 or len(right) > 1:
            # More than one finding shares this identity, and the schema offers nothing
            # that says which corresponds to which. Pairing them by list order would
            # manufacture a "changed" that is an artifact of ordering.
            deltas.append(
                FindingDelta(
                    rule_id=rule_id,
                    document=document,
                    field=field,
                    change=FindingChange.NOT_COMPARABLE,
                    before_count=len(left),
                    after_count=len(right),
                )
            )
            continue
        one_before = left[0] if left else None
        one_after = right[0] if right else None
        if one_before is None and one_after is not None:
            change = FindingChange.ADDED
            attributes: list[str] = []
        elif one_after is None and one_before is not None:
            change = FindingChange.REMOVED
            attributes = []
        elif one_before is not None and one_after is not None:
            attributes = _changed_attributes(one_before, one_after)
            change = FindingChange.CHANGED if attributes else FindingChange.UNCHANGED
        else:  # pragma: no cover - a key exists because at least one side holds it
            continue
        deltas.append(
            FindingDelta(
                rule_id=rule_id,
                document=document,
                field=field,
                change=change,
                before=FindingSide.of(one_before) if one_before else None,
                after=FindingSide.of(one_after) if one_after else None,
                changed_attributes=attributes,
                regression=_is_regression(one_before, one_after),
                before_count=len(left),
                after_count=len(right),
            )
        )
    return deltas


def _rule_ids_with_findings(report: InspectionReport) -> set[str]:
    return {finding.rule_id for finding in [*report.findings, *report.manual_review]}


def _skip_deltas(before: InspectionReport, after: InspectionReport) -> list[SkipDelta]:
    left = {skipped.rule_id: skipped for skipped in before.not_run}
    right = {skipped.rule_id: skipped for skipped in after.not_run}
    before_ran = _rule_ids_with_findings(before)
    after_ran = _rule_ids_with_findings(after)
    deltas: list[SkipDelta] = []
    for rule_id in sorted(set(left) | set(right)):
        in_before, in_after = left.get(rule_id), right.get(rule_id)
        title = (in_after or in_before).title  # type: ignore[union-attr]
        if in_before is not None and in_after is not None:
            change = (
                SkipChange.STILL_NOT_RUN
                if in_before.reason is in_after.reason
                else SkipChange.REASON_CHANGED
            )
        elif in_before is not None:
            # It did not run before. It only "ran this time" if the later report actually
            # holds a finding for it; otherwise the later report is silent about the rule
            # and this comparison must say so rather than imply the check came back.
            change = SkipChange.NOW_RAN if rule_id in after_ran else SkipChange.NOT_COMPARABLE
        else:
            change = SkipChange.NOW_NOT_RUN if rule_id in before_ran else SkipChange.NOT_COMPARABLE
        deltas.append(
            SkipDelta(
                rule_id=rule_id,
                title=title,
                change=change,
                before_reason=in_before.reason if in_before else None,
                after_reason=in_after.reason if in_after else None,
            )
        )
    return deltas


def _mismatches(before: InspectionReport, after: InspectionReport) -> list[ProvenanceMismatch]:
    pairs: Iterable[tuple[ProvenanceMismatch, object, object]] = (
        (
            ProvenanceMismatch.REPORT_SCHEMA_VERSION,
            *((before.report_schema_version, after.report_schema_version)),
        ),
        (ProvenanceMismatch.TOOL_VERSION, before.tool_version, after.tool_version),
        (ProvenanceMismatch.RULESET_VERSION, before.ruleset_version, after.ruleset_version),
        (ProvenanceMismatch.FILING_TYPE, before.filing_type, after.filing_type),
        (ProvenanceMismatch.INPUT_FINGERPRINT, before.input_fingerprint, after.input_fingerprint),
    )
    return [kind for kind, left, right in pairs if left != right]


def diff_reports(before: InspectionReport, after: InspectionReport) -> DiffReport:
    """Compare two loaded reports. Pure: reads no clock beyond stamping the output."""

    return DiffReport(
        tool_version=__version__,
        generated_at=datetime.now(UTC),
        before=ReportSide.of(before),
        after=ReportSide.of(after),
        mismatches=_mismatches(before, after),
        findings=_finding_deltas(before, after),
        not_run=_skip_deltas(before, after),
        disclaimer=diff_disclaimer(),
    )


def exit_code_for(diff: DiffReport) -> int:
    """``1`` when a failure is new or a finding became one, otherwise ``0``.

    Unreadable input never reaches here; the CLI returns ``2`` for that. A change that is
    not a regression — a failure that cleared, a message that was reworded — is not an
    error condition, so a correction cycle that fixed something exits ``0``.
    """

    return 1 if diff.regressions else 0
