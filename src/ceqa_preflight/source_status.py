"""Read a source-watch record and say what it means for each rule.

``scripts/watch_sources.py`` reports on *documents*. A rule cites a document, so a
document's verdict becomes a statement about the rules bound to it -- but only if the
translation keeps the watch's own distinctions intact. Three of them matter here, and
each one gets its own status rather than being folded into "unchanged":

* **A document the watch could not read was not examined.** It is not a document that
  turned out to be fine. The record says so by writing ``null`` rather than ``[]`` into
  ``passages_lost``, and that is the distinction the watch was built around. Reporting
  it as unchanged would publish an unread source as a verified one.
* **A document no record names says nothing about its rules.** A run narrowed with
  ``--document``, or a rule whose source is not a corpus document at all, leaves that
  rule ``not_watched`` -- again, not "unchanged". Silence is not a clean bill of health.
* **A rule bound to several documents takes the worst status among them**, so one
  unread document cannot be averaged away by two clean ones.

Because those distinctions live in the record's shape, this module refuses a record
whose shape contradicts itself: a document that claims to be ``unchanged`` while
reporting nothing examined, or examined while claiming to be ``unverifiable``, is not
readable in one of the two ways it describes itself, and guessing which half to believe
is the failure this module exists to prevent. It refuses an unrecognized status word for
the same reason.

This module reads a record. It fetches nothing, adopts nothing, and changes no rule.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .i18n import gettext as _

#: The one ``watch_schema_version`` this build knows how to read. Owned here rather than
#: imported from the watcher: the CLI reads a *record*, and a record that came from a
#: future watcher must be refused by name rather than parsed on the assumption that its
#: fields still mean what they meant.
SUPPORTED_WATCH_SCHEMA_VERSION = 1

#: The record's own vocabulary for a document, mirrored so an unrecognized word can be
#: named rather than mapped to whichever branch happens to be last.
_DOCUMENT_STATUSES = ("unchanged", "changed", "unverifiable")


class SourceStatusError(ValueError):
    """Raised when a source-watch record cannot be read as what it claims to be."""


class RuleSourceStatus(StrEnum):
    """What one watch record says about one rule's sources.

    Ordered worst first. ``NOT_WATCHED`` sits below ``NOT_EXAMINED`` because a record
    that never looked at a rule's source is a weaker statement than one that tried and
    could not read it, and neither is ``UNCHANGED``.
    """

    PASSAGES_LOST = "passages_lost"
    SOURCE_CHANGED = "source_changed"
    NOT_EXAMINED = "not_examined"
    NOT_WATCHED = "not_watched"
    UNCHANGED = "unchanged"


#: Worst first. Used to combine several documents into one rule status.
_SEVERITY: tuple[RuleSourceStatus, ...] = (
    RuleSourceStatus.PASSAGES_LOST,
    RuleSourceStatus.SOURCE_CHANGED,
    RuleSourceStatus.NOT_EXAMINED,
    RuleSourceStatus.NOT_WATCHED,
    RuleSourceStatus.UNCHANGED,
)


@dataclass(frozen=True)
class DocumentBinding:
    """One watched document, as it bears on one rule."""

    document_id: str
    document_status: str
    failure_kind: str | None
    rule_status: RuleSourceStatus

    def as_json(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "document_status": self.document_status,
            "failure_kind": self.failure_kind,
            "rule_status": str(self.rule_status),
        }


@dataclass(frozen=True)
class RuleSourceReport:
    """What the record says about one rule, and which documents said it."""

    rule_id: str
    status: RuleSourceStatus
    documents: tuple[DocumentBinding, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "documents": [binding.as_json() for binding in self.documents],
        }


@dataclass(frozen=True)
class WatchRecord:
    """A validated source-watch record: the fields this reader is entitled to trust."""

    path: Path
    checked_at: str
    read_from: str
    documents: tuple[Mapping[str, Any], ...]


def _require_mapping(value: Any, path: Path) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SourceStatusError(
            _("{path} is not a source-watch record: its top level is not an object.").format(
                path=path
            )
        )
    return value


def load_watch_record(path: Path) -> WatchRecord:
    """Read and validate one source-watch record, or refuse it by name."""

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise SourceStatusError(_("No source-watch record at {path}.").format(path=path)) from error
    except OSError as error:
        raise SourceStatusError(
            _("Could not read the source-watch record at {path}: {reason}").format(
                path=path, reason=error.strerror or type(error).__name__
            )
        ) from error
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SourceStatusError(
            _("{path} is not valid JSON: {reason}").format(path=path, reason=error.msg)
        ) from error
    record = _require_mapping(document, path)
    if "watch_schema_version" not in record:
        raise SourceStatusError(
            _("{path} declares no watch_schema_version, so it cannot be read safely.").format(
                path=path
            )
        )
    declared = record["watch_schema_version"]
    if declared != SUPPORTED_WATCH_SCHEMA_VERSION:
        raise SourceStatusError(
            _(
                "{path} declares watch_schema_version {declared}; this build reads "
                "version {supported}."
            ).format(path=path, declared=declared, supported=SUPPORTED_WATCH_SCHEMA_VERSION)
        )
    documents = record.get("documents")
    if not isinstance(documents, list):
        raise SourceStatusError(
            _("{path} carries no documents list, so it reports on nothing.").format(path=path)
        )
    entries: list[Mapping[str, Any]] = []
    for index, entry in enumerate(documents):
        entries.append(_validated_document(entry, index=index, path=path))
    return WatchRecord(
        path=path,
        checked_at=str(record.get("checked_at", "")),
        read_from=str(record.get("read_from", "")),
        documents=tuple(entries),
    )


def _validated_document(entry: Any, *, index: int, path: Path) -> Mapping[str, Any]:
    if not isinstance(entry, dict):
        raise SourceStatusError(
            _("{path}: document {index} is not an object.").format(path=path, index=index)
        )
    document_id = entry.get("id")
    if not isinstance(document_id, str) or not document_id:
        raise SourceStatusError(
            _("{path}: document {index} has no id.").format(path=path, index=index)
        )
    status = entry.get("status")
    if status not in _DOCUMENT_STATUSES:
        # `repr` is applied here rather than written as `{status!r}` in the message:
        # `scripts/check_i18n.py` recognizes `{name}` and nothing else, so a conversion
        # flag inside the placeholder would make the token invisible to the parity gate
        # and a translation could drop the value without failing anything.
        raise SourceStatusError(
            _("{path}: document {document_id} reports an unknown status {status}.").format(
                path=path, document_id=document_id, status=repr(status)
            )
        )
    examined = entry.get("passages_lost") is not None
    if examined and status == "unverifiable":
        raise SourceStatusError(
            _(
                "{path}: document {document_id} is recorded as unverifiable and as "
                "examined at the same time."
            ).format(path=path, document_id=document_id)
        )
    if not examined and status != "unverifiable":
        raise SourceStatusError(
            _(
                "{path}: document {document_id} is recorded as {status} but reports "
                "nothing examined."
            ).format(path=path, document_id=document_id, status=status)
        )
    return entry


def _document_rule_status(entry: Mapping[str, Any], rule_id: str) -> RuleSourceStatus:
    status = entry["status"]
    if status == "unverifiable":
        return RuleSourceStatus.NOT_EXAMINED
    if status == "unchanged":
        return RuleSourceStatus.UNCHANGED
    lost = entry.get("rules_with_lost_passages") or []
    if rule_id in lost:
        return RuleSourceStatus.PASSAGES_LOST
    return RuleSourceStatus.SOURCE_CHANGED


def _worst(statuses: Iterable[RuleSourceStatus]) -> RuleSourceStatus | None:
    # Materialized before the scan: ``statuses`` may be a one-shot iterator, and
    # rebuilding the set inside the comprehension would exhaust it after the first
    # comparison and silently return whichever status happened to be ranked first.
    present = set(statuses)
    for status in _SEVERITY:
        if status in present:
            return status
    return None


def rule_source_reports(
    record: WatchRecord, rule_ids: Sequence[str]
) -> dict[str, RuleSourceReport]:
    """One report per rule id, in the order given.

    A rule the record binds to no document is ``not_watched``. It is not folded into
    ``unchanged``, because a record that never read a rule's source has said nothing
    about it.
    """

    reports: dict[str, RuleSourceReport] = {}
    for rule_id in rule_ids:
        bindings = tuple(
            DocumentBinding(
                document_id=str(entry["id"]),
                document_status=str(entry["status"]),
                failure_kind=(
                    None if entry.get("failure_kind") is None else str(entry["failure_kind"])
                ),
                rule_status=_document_rule_status(entry, rule_id),
            )
            for entry in record.documents
            if rule_id in (entry.get("rules_bound") or [])
        )
        status = _worst(binding.rule_status for binding in bindings)
        reports[rule_id] = RuleSourceReport(
            rule_id=rule_id,
            status=RuleSourceStatus.NOT_WATCHED if status is None else status,
            documents=bindings,
        )
    return reports


def status_label(status: RuleSourceStatus) -> str:
    """A localized one-line reading of a rule status.

    A function rather than a module constant on purpose: a constant would be built at
    import, freezing whichever locale happened to be active first.
    """

    labels = {
        RuleSourceStatus.UNCHANGED: _("source unchanged"),
        RuleSourceStatus.SOURCE_CHANGED: _(
            "source changed; this rule's retained passages still occur"
        ),
        RuleSourceStatus.PASSAGES_LOST: _(
            "source changed; retained passages for this rule no longer occur"
        ),
        RuleSourceStatus.NOT_EXAMINED: _("not examined; a bound source could not be read"),
        RuleSourceStatus.NOT_WATCHED: _("not watched; this record names no source for it"),
    }
    return labels[status]


def record_preamble(record: WatchRecord) -> str:
    """The sentence that keeps a listing from reading as an adoption.

    It names the document count on purpose. A record written by a run narrowed with
    ``--document`` covers part of the corpus, and a rule whose other sources were never
    in that run would otherwise read as cleanly checked. This reader has no way to know
    what a record left out -- the shipped package carries no corpus manifest to compare
    against -- so the honest move is to publish the record's own extent beside its
    verdicts.
    """

    return _(
        "Source status from {path}, read {read_from} at {checked_at}, over the "
        "{documents} document(s) that record names. It reports what the sources said "
        "when they were read; a source no record names is not a source that was "
        "checked. It changes no rule and is not a review."
    ).format(
        path=record.path,
        read_from=record.read_from or _("an unrecorded origin"),
        checked_at=record.checked_at or _("an unrecorded time"),
        documents=len(record.documents),
    )
