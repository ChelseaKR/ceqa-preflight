"""Privacy-preserving aggregation for permissioned CEQA Preflight pilots."""

from __future__ import annotations

import csv
import statistics
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from ceqa_preflight.models import FilingType, FindingStatus, StrictModel

_MAX_ROWS = 10_000
_DANGEROUS_SPREADSHEET_PREFIXES = ("=", "+", "-", "@")

REVIEW_HEADERS = (
    "package_id",
    "filing_type",
    "rule_id",
    "finding_status",
    "disposition",
    "severity",
    "elapsed_seconds",
)
BASELINE_HEADERS = ("package_id", "filing_type", "severity", "was_missed")


class ReviewDisposition(StrEnum):
    """A qualified reviewer's controlled outcome for an automated finding."""

    TRUE_POSITIVE = "true_positive"
    FALSE_POSITIVE = "false_positive"
    INDETERMINATE = "indeterminate"
    NOT_ACTIONABLE = "not_actionable"


class Severity(StrEnum):
    """Severity labels used only for pilot aggregate evaluation."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _safe_cell(value: str) -> str:
    """Reject free text and spreadsheet-formula-like values from pilot exports."""

    if not value or len(value) > 128 or "\n" in value or "\r" in value:
        raise ValueError("must be a non-empty, single-line value of at most 128 characters")
    if value.startswith(_DANGEROUS_SPREADSHEET_PREFIXES):
        raise ValueError("must not begin with a spreadsheet formula prefix")
    return value


class FindingReview(StrictModel):
    """One controlled-label review of an automated finding; no filing content."""

    package_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{2,63}$")
    filing_type: FilingType
    rule_id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{2,63}$")
    finding_status: FindingStatus
    disposition: ReviewDisposition
    severity: Severity
    elapsed_seconds: float = Field(ge=0, le=3600)

    @field_validator("package_id", "rule_id", mode="before")
    @classmethod
    def require_safe_identifier(cls, value: object) -> str:
        return _safe_cell(str(value))

    @model_validator(mode="after")
    def require_automated_outcome(self) -> FindingReview:
        if self.finding_status not in {FindingStatus.WARNING, FindingStatus.FAILURE}:
            raise ValueError("finding_status must be warning or failure for a pilot review")
        return self


class BaselineIssue(StrictModel):
    """A manual-baseline issue used to estimate false-negative risk."""

    package_id: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_-]{2,63}$")
    filing_type: FilingType
    severity: Severity
    was_missed: bool

    @field_validator("package_id", mode="before")
    @classmethod
    def require_safe_identifier(cls, value: object) -> str:
        return _safe_cell(str(value))


class PilotSummary(StrictModel):
    """Aggregate-only measurement output for a permissioned pilot."""

    reviewed_findings: int = Field(ge=0)
    reviewed_packages: int = Field(ge=0)
    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    indeterminate: int = Field(ge=0)
    not_actionable: int = Field(ge=0)
    actionable_precision: float | None = Field(default=None, ge=0, le=1)
    median_report_seconds: float | None = Field(default=None, ge=0)
    high_severity_baseline_issues: int = Field(ge=0)
    high_severity_missed: int = Field(ge=0)
    high_severity_false_negative_rate: float | None = Field(default=None, ge=0, le=1)
    go_no_go: str
    reasons: list[str]


class PilotDataError(ValueError):
    """Raised for a malformed or privacy-unsafe pilot evidence file."""


def _read_rows(path: Path, expected_headers: tuple[str, ...]) -> Iterable[dict[str, str]]:
    if path.suffix.casefold() != ".csv":
        raise PilotDataError(f"{path.name}: expected a .csv file")
    try:
        with path.open("r", encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            if tuple(reader.fieldnames or ()) != expected_headers:
                expected = ", ".join(expected_headers)
                raise PilotDataError(f"{path.name}: headers must be exactly: {expected}")
            for index, row in enumerate(reader, start=2):
                if index > _MAX_ROWS + 1:
                    raise PilotDataError(f"{path.name}: exceeds {_MAX_ROWS} rows")
                if None in row or any(value is None for value in row.values()):
                    raise PilotDataError(f"{path.name}:{index}: missing a required value")
                yield {key: value or "" for key, value in row.items() if key is not None}
    except OSError as error:
        raise PilotDataError(f"cannot read {path}: {error}") from error


def _validated_rows[T: StrictModel](
    path: Path, expected_headers: tuple[str, ...], model: type[T]
) -> list[T]:
    items: list[T] = []
    for index, row in enumerate(_read_rows(path, expected_headers), start=2):
        try:
            items.append(model.model_validate(row))
        except ValueError as error:
            raise PilotDataError(f"{path.name}:{index}: {error}") from error
    return items


def _review_metrics(
    reviews: list[FindingReview],
) -> tuple[dict[ReviewDisposition, int], float | None, dict[str, float]]:
    review_keys = {(item.package_id, item.rule_id, item.finding_status) for item in reviews}
    if len(review_keys) != len(reviews):
        raise PilotDataError("review file: duplicate package_id, rule_id, and finding_status rows")

    counts = {disposition: 0 for disposition in ReviewDisposition}
    for review in reviews:
        counts[review.disposition] += 1
    precision_denominator = (
        counts[ReviewDisposition.TRUE_POSITIVE] + counts[ReviewDisposition.FALSE_POSITIVE]
    )
    precision = (
        counts[ReviewDisposition.TRUE_POSITIVE] / precision_denominator
        if precision_denominator
        else None
    )
    elapsed_by_package: dict[str, float] = {}
    for review in reviews:
        previous = elapsed_by_package.setdefault(review.package_id, review.elapsed_seconds)
        if previous != review.elapsed_seconds:
            raise PilotDataError(
                "review file: elapsed_seconds must match for every row of a package"
            )
    return counts, precision, elapsed_by_package


def _pilot_reasons(
    precision: float | None,
    false_negative_rate: float | None,
    median_seconds: float | None,
) -> list[str]:
    reasons: list[str] = []
    if precision is None:
        reasons.append("No true/false-positive labels are available for precision.")
    elif precision < 0.90:
        reasons.append("Actionable automated-finding precision is below the 90% pilot threshold.")
    if false_negative_rate is None:
        reasons.append(
            "No high-severity manual baseline issues are available for false-negative review."
        )
    elif false_negative_rate >= 0.05:
        reasons.append("High-severity false-negative rate is at or above the 5% pilot threshold.")
    if median_seconds is None:
        reasons.append("No package report timings are available.")
    elif median_seconds >= 300:
        reasons.append("Median report time is at or above the five-minute pilot threshold.")
    return reasons


def summarize_pilot(reviews_path: Path, baseline_path: Path) -> PilotSummary:
    """Validate controlled-label pilot files and return only aggregate measures."""

    reviews = _validated_rows(reviews_path, REVIEW_HEADERS, FindingReview)
    baselines = _validated_rows(baseline_path, BASELINE_HEADERS, BaselineIssue)
    counts, precision, elapsed_by_package = _review_metrics(reviews)
    high_issues = [issue for issue in baselines if issue.severity is Severity.HIGH]
    high_missed = sum(issue.was_missed for issue in high_issues)
    false_negative_rate = high_missed / len(high_issues) if high_issues else None
    median_seconds = statistics.median(elapsed_by_package.values()) if elapsed_by_package else None
    reasons = _pilot_reasons(precision, false_negative_rate, median_seconds)
    go_no_go = "go" if not reasons else "no_go"
    if go_no_go == "go":
        reasons.append(
            "All quantitative pilot thresholds are met; complete qualitative review before release."
        )

    return PilotSummary(
        reviewed_findings=len(reviews),
        reviewed_packages=len(elapsed_by_package),
        true_positives=counts[ReviewDisposition.TRUE_POSITIVE],
        false_positives=counts[ReviewDisposition.FALSE_POSITIVE],
        indeterminate=counts[ReviewDisposition.INDETERMINATE],
        not_actionable=counts[ReviewDisposition.NOT_ACTIONABLE],
        actionable_precision=precision,
        median_report_seconds=median_seconds,
        high_severity_baseline_issues=len(high_issues),
        high_severity_missed=high_missed,
        high_severity_false_negative_rate=false_negative_rate,
        go_no_go=go_no_go,
        reasons=reasons,
    )


def write_pilot_templates(directory: Path) -> tuple[Path, Path]:
    """Create non-overwriting controlled-label CSV templates for a pilot."""

    directory.mkdir(parents=True, exist_ok=True)
    review_path = directory / "finding-review.csv"
    baseline_path = directory / "manual-baseline.csv"
    for path, headers in ((review_path, REVIEW_HEADERS), (baseline_path, BASELINE_HEADERS)):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite existing pilot template: {path}")
        with path.open("w", encoding="utf-8", newline="") as destination:
            csv.writer(destination).writerow(headers)
    return review_path, baseline_path
