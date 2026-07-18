"""Typed contracts shared by loaders, inspectors, rules, and reporters."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class Confidence(StrEnum):
    """Confidence in extracted or inferred evidence."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceCitation(StrictModel):
    """A current, traceable source for a rule or report finding."""

    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
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


class InspectionReport(StrictModel):
    """Versioned, JSON-serializable output for an inspection run."""

    report_schema_version: str = Field(default="1.0")
    tool_version: str = Field(min_length=1)
    ruleset_version: str = Field(min_length=1)
    generated_at: datetime
    input_fingerprint: str = Field(min_length=1)
    filing_type: FilingType
    findings: list[Finding] = Field(default_factory=list)
    manual_review: list[Finding] = Field(default_factory=list)
    disclaimer: str = Field(min_length=1)
