"""Typed contracts shared by loaders, inspectors, rules, and reporters."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Base model that rejects unknown fields and trims input strings."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FilingType(StrEnum):
    """Filing types supported by the initial product scope."""

    NOD = "NOD"
    NOE = "NOE"


class FindingStatus(StrEnum):
    """User-facing outcome levels for a check."""

    # This is a user-facing validation status, not a credential.
    PASS = "pass"  # nosec B105
    WARNING = "warning"
    FAILURE = "failure"
    MANUAL = "manual"


class SkipReason(StrEnum):
    """Why an applicable rule did not run during a check."""

    EXPERIMENTAL_NOT_INCLUDED = "experimental_not_included"
    WITHDRAWN = "withdrawn"
    NOT_SELECTED = "not_selected"
    EXCLUDED_BY_REQUEST = "excluded_by_request"


class Confidence(StrEnum):
    """Confidence in extracted or inferred evidence."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceKind(StrEnum):
    """What kind of authority a citation carries, so a reader never mistakes one for another."""

    OFFICIAL = "official"  # State of California guidance the rule is grounded in
    TECHNICAL_REFERENCE = "technical_reference"  # a non-CEQA technical reference (e.g. OWASP)
    PROJECT_ADVISORY = "project_advisory"  # this project's own documented reasoning


class SourceCitation(StrictModel):
    """A current, traceable source for a rule or report finding."""

    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    kind: SourceKind = SourceKind.OFFICIAL
    section: str | None = None
    effective_date: str | None = None
    accessed_date: str | None = None

    @field_validator("url")
    @classmethod
    def require_http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source URL must be an absolute HTTP(S) URL")
        return value


class Evidence(StrictModel):
    """Structured evidence supporting a finding without embedding source files."""

    details: dict[str, Any] = Field(default_factory=dict)


class Finding(StrictModel):
    """A deterministic result from one versioned rule."""

    rule_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    status: FindingStatus
    title: str = Field(min_length=1)
    message: str = Field(min_length=1)
    document: str | None = None
    page: int | None = Field(default=None, ge=1)
    field: str | None = None
    evidence: Evidence = Field(default_factory=Evidence)
    remediation: str = Field(min_length=1)
    source: SourceCitation | None = None
    confidence: Confidence = Confidence.HIGH


class SkippedCheck(StrictModel):
    """A rule that applied to this filing type but did not run, and why.

    A report that lists only what ran cannot be read as a statement about the whole
    package: a reader has no way to tell an all-clear from an all-clear with checks
    removed. Every skip is recorded here so a clean result always carries its own scope.
    """

    rule_id: str = Field(min_length=1)
    rule_version: str = Field(min_length=1)
    title: str = Field(min_length=1)
    reason: SkipReason
    detail: str = Field(min_length=1)
    source: SourceCitation | None = None


def _normalize_relative_path(value: str) -> str:
    """Return a safe, POSIX-style path that cannot escape a package root."""

    if not value or "\x00" in value:
        raise ValueError("document path must be a non-empty, non-null string")

    windows_path = PureWindowsPath(value)
    candidate = value.replace("\\", "/")
    posix_path = PurePosixPath(candidate)

    if windows_path.is_absolute() or windows_path.drive or posix_path.is_absolute():
        raise ValueError("document path must be relative to the package root")
    if any(part in {"", ".", ".."} for part in posix_path.parts):
        raise ValueError("document path cannot contain empty, current, or parent segments")

    return posix_path.as_posix()


class DocumentEntry(StrictModel):
    """A document expected in the package."""

    path: str = Field(min_length=1)
    category: str | None = None
    primary: bool = False

    @field_validator("path")
    @classmethod
    def normalize_relative_path(cls, value: str) -> str:
        return _normalize_relative_path(value)


class ProjectMetadata(StrictModel):
    """Manifest data intentionally supplied for conservative consistency checks."""

    title: str = Field(min_length=1)
    description: str | None = None
    sch_number: str | None = None
    lead_agency: str | None = None
    county: str | None = None
    city_or_community: str | None = None


class Contact(StrictModel):
    """A project or agency contact represented in a manifest."""

    name: str = Field(min_length=1)
    authority: str | None = None
    role: str = Field(min_length=1)


class PackageManifest(StrictModel):
    """The user-supplied, versioned description of an intended filing package."""

    schema_version: str = Field(default="1.0")
    filing_type: FilingType
    project: ProjectMetadata
    contacts: list[Contact] = Field(default_factory=list)
    documents: list[DocumentEntry] = Field(min_length=1)

    @field_validator("schema_version")
    @classmethod
    def require_supported_schema_major(cls, value: str) -> str:
        major, separator, _ = value.partition(".")
        if not separator or major != "1":
            raise ValueError("unsupported manifest schema major; expected 1.x")
        return value

    @model_validator(mode="after")
    def reject_duplicate_document_paths(self) -> PackageManifest:
        """Refuse two declarations of one path instead of keeping whichever came last.

        The checker builds its declaration lookup as a dict keyed by path, so a manifest
        that declared the same file twice with conflicting ``category`` or ``primary``
        values silently kept only the last entry. Every downstream rule then read the
        surviving declaration as if it were the only one the person wrote, and the report
        contradicted the manifest with no diagnostic pointing at the cause: MAN-001 and
        CAT-001, whose whole purpose is catching manifest inconsistency, both passed
        cleanly because neither could see that a duplicate existed at all (issue #55).

        Rejecting at load time fails closed, and matches how strictly the rest of this
        model already treats manifest input. Paths are compared after normalization, so
        ``a\\b.pdf`` and ``a/b.pdf`` are the one declaration they resolve to.
        """

        seen: set[str] = set()
        duplicates: list[str] = []
        for entry in self.documents:
            if entry.path in seen and entry.path not in duplicates:
                duplicates.append(entry.path)
            seen.add(entry.path)
        if duplicates:
            raise ValueError(
                "manifest declares the same document path more than once, so the "
                "conflicting declarations cannot be resolved: " + ", ".join(duplicates)
            )
        return self


class InspectionReport(StrictModel):
    """Versioned, JSON-serializable output for an inspection run."""

    report_schema_version: str = Field(default="1.1")
    tool_version: str = Field(min_length=1)
    ruleset_version: str = Field(min_length=1)
    generated_at: datetime
    input_fingerprint: str = Field(min_length=1)
    filing_type: FilingType
    findings: list[Finding] = Field(default_factory=list)
    manual_review: list[Finding] = Field(default_factory=list)
    not_run: list[SkippedCheck] = Field(default_factory=list)
    disclaimer: str = Field(min_length=1)
