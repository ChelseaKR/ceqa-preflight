"""Privacy-preserving aggregation for permissioned CEQA Preflight pilots."""

from __future__ import annotations

import csv
import itertools
import statistics
from collections import defaultdict
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path

from pydantic import Field, field_validator, model_validator

from ceqa_preflight.intervals import CONFIDENCE_LEVEL, cohens_kappa, proportion, wilson_interval
from ceqa_preflight.models import FilingType, FindingStatus, StrictModel
from ceqa_preflight.synth import SyntheticDefect

_MAX_ROWS = 10_000
_DANGEROUS_SPREADSHEET_PREFIXES = ("=", "+", "-", "@")

# A permissioned pilot has a handful of qualified reviewers, and reviewer agreement is
# computed over every pair. Refusing an implausible number of distinct reviewer ids keeps
# that quadratic step bounded by something a person chose rather than by the row cap.
_MAX_REVIEWERS = 64

# `docs/pilot-partner-kit.md`: "Each filing-specific rule needs two independent qualified
# CEQA reviewers before it can be activated." This counts *coverage* -- how many distinct
# reviewers labelled the rule's findings -- and never claims approval. Approval is the
# rubric's "Approve / revise / do not activate", which the same document keeps in the
# participant's private register and out of the evidence file on purpose.
REVIEWER_COVERAGE_THRESHOLD = 2

REVIEW_HEADERS = (
    "package_id",
    "filing_type",
    "rule_id",
    "finding_status",
    "disposition",
    "severity",
    "elapsed_seconds",
    "reviewer_id",
    "synth_seed",
    "expected_defect",
)
# The header set before per-reviewer evidence existed. Recognised only so an operator
# holding a template from an earlier version gets told what changed rather than a bare
# list of ten column names.
LEGACY_REVIEW_HEADERS = REVIEW_HEADERS[:7]
BASELINE_HEADERS = ("package_id", "filing_type", "severity", "was_missed")

_OPAQUE_ID = r"^[A-Z0-9][A-Z0-9_-]{2,63}$"


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

    package_id: str = Field(pattern=_OPAQUE_ID)
    filing_type: FilingType
    rule_id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{2,63}$")
    finding_status: FindingStatus
    disposition: ReviewDisposition
    severity: Severity
    elapsed_seconds: float = Field(ge=0, le=3600)
    reviewer_id: str = Field(pattern=_OPAQUE_ID)
    synth_seed: str | None = Field(default=None, pattern=_OPAQUE_ID)
    expected_defect: SyntheticDefect | None = None

    @field_validator("package_id", "rule_id", "reviewer_id", mode="before")
    @classmethod
    def require_safe_identifier(cls, value: object) -> str:
        return _safe_cell(str(value))

    @field_validator("synth_seed", "expected_defect", mode="before")
    @classmethod
    def blank_is_absent(cls, value: object) -> object:
        """An empty CSV cell is an absent optional value, not the string ``""``."""

        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def require_automated_outcome(self) -> FindingReview:
        if self.finding_status not in {FindingStatus.WARNING, FindingStatus.FAILURE}:
            raise ValueError("finding_status must be warning or failure for a pilot review")
        return self

    @model_validator(mode="after")
    def require_a_whole_calibration_row(self) -> FindingReview:
        """A calibration row states both which synthetic run it came from and what was seeded.

        Half of the pair alone cannot be interpreted: a row with a seeded defect but no
        synthetic run does not say which generated package it belongs to, and a row naming
        a run with no seeded defect would be counted with the real packages, which is the
        one thing a synthetic row must never be.
        """

        if (self.synth_seed is None) != (self.expected_defect is None):
            raise ValueError(
                "synth_seed and expected_defect must be given together or both left empty"
            )
        return self

    @property
    def is_calibration(self) -> bool:
        """True for a row about a synthetic package with a known seeded defect."""

        return self.expected_defect is not None


class BaselineIssue(StrictModel):
    """A manual-baseline issue used to estimate false-negative risk."""

    package_id: str = Field(pattern=_OPAQUE_ID)
    filing_type: FilingType
    severity: Severity
    was_missed: bool

    @field_validator("package_id", mode="before")
    @classmethod
    def require_safe_identifier(cls, value: object) -> str:
        return _safe_cell(str(value))


class RulePrecision(StrictModel):
    """Precision for one rule, with the interval that says how little it rests on.

    ``precision`` and the interval bounds are ``None`` together, and only when
    ``labelled_findings`` is zero. Nothing here is ever rendered as ``0`` for absent data:
    a rule nobody labelled has no precision, which is not the same as a precision of zero.
    """

    rule_id: str
    labelled_findings: int = Field(ge=0)
    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    precision: float | None = Field(default=None, ge=0, le=1)
    precision_interval_low: float | None = Field(default=None, ge=0, le=1)
    precision_interval_high: float | None = Field(default=None, ge=0, le=1)
    independent_reviewers: int = Field(ge=0)
    meets_reviewer_coverage: bool


class ReviewerAgreement(StrictModel):
    """Agreement between one pair of reviewers on one rule's findings.

    ``cohens_kappa`` is ``None`` when ``kappa_undefined`` is true: both reviewers used a
    single identical label throughout, chance agreement is total, and kappa's denominator
    is zero. That is reported as undefined rather than as perfect or as zero, either of
    which would be a number no data supports.
    """

    rule_id: str
    reviewer_a: str
    reviewer_b: str
    compared_findings: int = Field(ge=0)
    agreed_findings: int = Field(ge=0)
    percent_agreement: float | None = Field(default=None, ge=0, le=1)
    cohens_kappa: float | None = Field(default=None, ge=-1, le=1)
    kappa_undefined: bool


class ReviewerCalibration(StrictModel):
    """One reviewer's record against the known seeded defects of synthetic packages.

    Calibration rows never enter the precision, timing or go/no-go figures: a synthetic
    package is built to contain the defect its rule looks for, so counting it as evidence
    of accuracy on real filings would inflate the very number the pilot exists to measure.
    """

    reviewer_id: str
    expected_defect: str
    seeded_findings: int = Field(ge=0)
    identified: int = Field(ge=0)
    missed: int = Field(ge=0)


class PilotSummary(StrictModel):
    """Aggregate-only measurement output for a permissioned pilot."""

    reviewed_findings: int = Field(ge=0)
    reviewed_packages: int = Field(ge=0)
    true_positives: int = Field(ge=0)
    false_positives: int = Field(ge=0)
    indeterminate: int = Field(ge=0)
    not_actionable: int = Field(ge=0)
    actionable_precision: float | None = Field(default=None, ge=0, le=1)
    actionable_precision_interval_low: float | None = Field(default=None, ge=0, le=1)
    actionable_precision_interval_high: float | None = Field(default=None, ge=0, le=1)
    interval_confidence_level: float = Field(default=CONFIDENCE_LEVEL, gt=0, lt=1)
    median_report_seconds: float | None = Field(default=None, ge=0)
    high_severity_baseline_issues: int = Field(ge=0)
    high_severity_missed: int = Field(ge=0)
    high_severity_false_negative_rate: float | None = Field(default=None, ge=0, le=1)
    reviewer_coverage_threshold: int = Field(ge=1)
    rules: list[RulePrecision]
    reviewer_agreement: list[ReviewerAgreement]
    calibration: list[ReviewerCalibration]
    calibration_findings: int = Field(ge=0)
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
            found = tuple(reader.fieldnames or ())
            if found != expected_headers:
                expected = ", ".join(expected_headers)
                hint = ""
                if found == LEGACY_REVIEW_HEADERS:
                    added = ", ".join(REVIEW_HEADERS[len(LEGACY_REVIEW_HEADERS) :])
                    hint = (
                        f" this file uses the earlier template; add the columns: {added} "
                        "(reviewer_id is required, the other two are for calibration rows)"
                    )
                raise PilotDataError(f"{path.name}: headers must be exactly: {expected}.{hint}")
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


def _check_review_integrity(reviews: list[FindingReview]) -> None:
    """Structural checks that apply to every row, calibration rows included."""

    review_keys = {
        (item.package_id, item.rule_id, item.finding_status, item.reviewer_id) for item in reviews
    }
    if len(review_keys) != len(reviews):
        raise PilotDataError(
            "review file: duplicate package_id, rule_id, finding_status, and reviewer_id rows"
        )
    reviewers = {item.reviewer_id for item in reviews}
    if len(reviewers) > _MAX_REVIEWERS:
        raise PilotDataError(f"review file: more than {_MAX_REVIEWERS} distinct reviewer_id values")
    synthetic = {item.package_id for item in reviews if item.is_calibration}
    field = {item.package_id for item in reviews if not item.is_calibration}
    both = sorted(synthetic & field)
    if both:
        raise PilotDataError(
            "review file: a package_id is either synthetic or a real filing package, not both: "
            + ", ".join(both)
        )


def _review_metrics(
    reviews: list[FindingReview],
) -> tuple[dict[ReviewDisposition, int], float | None, dict[str, float]]:
    counts = {disposition: 0 for disposition in ReviewDisposition}
    for review in reviews:
        counts[review.disposition] += 1
    precision = proportion(
        counts[ReviewDisposition.TRUE_POSITIVE],
        counts[ReviewDisposition.TRUE_POSITIVE] + counts[ReviewDisposition.FALSE_POSITIVE],
    )
    elapsed_by_package: dict[str, float] = {}
    for review in reviews:
        previous = elapsed_by_package.setdefault(review.package_id, review.elapsed_seconds)
        if previous != review.elapsed_seconds:
            raise PilotDataError(
                "review file: elapsed_seconds must match for every row of a package"
            )
    return counts, precision, elapsed_by_package


def _rule_precisions(reviews: list[FindingReview]) -> list[RulePrecision]:
    """Precision, interval and reviewer coverage for each rule that was reviewed."""

    by_rule: dict[str, list[FindingReview]] = defaultdict(list)
    for review in reviews:
        by_rule[review.rule_id].append(review)

    results: list[RulePrecision] = []
    for rule_id in sorted(by_rule):
        rows = by_rule[rule_id]
        true_positives = sum(
            1 for row in rows if row.disposition is ReviewDisposition.TRUE_POSITIVE
        )
        false_positives = sum(
            1 for row in rows if row.disposition is ReviewDisposition.FALSE_POSITIVE
        )
        labelled = true_positives + false_positives
        interval = wilson_interval(true_positives, labelled)
        reviewers = {row.reviewer_id for row in rows}
        results.append(
            RulePrecision(
                rule_id=rule_id,
                labelled_findings=labelled,
                true_positives=true_positives,
                false_positives=false_positives,
                precision=proportion(true_positives, labelled),
                precision_interval_low=None if interval is None else interval.low,
                precision_interval_high=None if interval is None else interval.high,
                independent_reviewers=len(reviewers),
                meets_reviewer_coverage=len(reviewers) >= REVIEWER_COVERAGE_THRESHOLD,
            )
        )
    return results


def _reviewer_agreement(reviews: list[FindingReview]) -> list[ReviewerAgreement]:
    """Percent agreement and Cohen's kappa for every reviewer pair that shares findings.

    A pair with no finding in common produces no row at all. Emitting one with zeroes
    would put a number where there is no comparison.
    """

    labels: dict[str, dict[str, dict[tuple[str, FindingStatus], str]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for review in reviews:
        key = (review.package_id, review.finding_status)
        labels[review.rule_id][review.reviewer_id][key] = review.disposition.value

    results: list[ReviewerAgreement] = []
    for rule_id in sorted(labels):
        by_reviewer = labels[rule_id]
        for first, second in itertools.combinations(sorted(by_reviewer), 2):
            shared = sorted(by_reviewer[first].keys() & by_reviewer[second].keys())
            if not shared:
                continue
            agreement = cohens_kappa(
                [by_reviewer[first][key] for key in shared],
                [by_reviewer[second][key] for key in shared],
            )
            results.append(
                ReviewerAgreement(
                    rule_id=rule_id,
                    reviewer_a=first,
                    reviewer_b=second,
                    compared_findings=agreement.compared,
                    agreed_findings=agreement.agreed,
                    percent_agreement=agreement.percent_agreement,
                    cohens_kappa=agreement.kappa,
                    kappa_undefined=agreement.kappa_undefined,
                )
            )
    return results


def _calibration(reviews: list[FindingReview]) -> list[ReviewerCalibration]:
    """Score each reviewer against the defects a synthetic package was built to contain.

    The seeded defect is ground truth, so a warning or failure raised on it is a true
    positive by construction. A reviewer who labels it anything else -- including
    ``indeterminate`` -- did not identify a defect that is known to be there, and that is
    recorded as a miss rather than passed over.
    """

    seeded: dict[tuple[str, str], int] = defaultdict(int)
    identified: dict[tuple[str, str], int] = defaultdict(int)
    for review in reviews:
        defect = review.expected_defect
        if defect is None:  # pragma: no cover - callers pass calibration rows only
            continue
        key = (review.reviewer_id, defect.value)
        seeded[key] += 1
        if review.disposition is ReviewDisposition.TRUE_POSITIVE:
            identified[key] += 1

    return [
        ReviewerCalibration(
            reviewer_id=reviewer_id,
            expected_defect=defect,
            seeded_findings=seeded[(reviewer_id, defect)],
            identified=identified[(reviewer_id, defect)],
            missed=seeded[(reviewer_id, defect)] - identified[(reviewer_id, defect)],
        )
        for reviewer_id, defect in sorted(seeded)
    ]


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
    _check_review_integrity(reviews)
    calibration_rows = [review for review in reviews if review.is_calibration]
    field_rows = [review for review in reviews if not review.is_calibration]

    counts, precision, elapsed_by_package = _review_metrics(field_rows)
    high_issues = [issue for issue in baselines if issue.severity is Severity.HIGH]
    high_missed = sum(issue.was_missed for issue in high_issues)
    false_negative_rate = proportion(high_missed, len(high_issues))
    median_seconds = statistics.median(elapsed_by_package.values()) if elapsed_by_package else None
    reasons = _pilot_reasons(precision, false_negative_rate, median_seconds)
    go_no_go = "go" if not reasons else "no_go"
    if go_no_go == "go":
        reasons.append(
            "All quantitative pilot thresholds are met; complete qualitative review before release."
        )
    interval = wilson_interval(
        counts[ReviewDisposition.TRUE_POSITIVE],
        counts[ReviewDisposition.TRUE_POSITIVE] + counts[ReviewDisposition.FALSE_POSITIVE],
    )

    return PilotSummary(
        reviewed_findings=len(field_rows),
        reviewed_packages=len(elapsed_by_package),
        true_positives=counts[ReviewDisposition.TRUE_POSITIVE],
        false_positives=counts[ReviewDisposition.FALSE_POSITIVE],
        indeterminate=counts[ReviewDisposition.INDETERMINATE],
        not_actionable=counts[ReviewDisposition.NOT_ACTIONABLE],
        actionable_precision=precision,
        actionable_precision_interval_low=None if interval is None else interval.low,
        actionable_precision_interval_high=None if interval is None else interval.high,
        interval_confidence_level=CONFIDENCE_LEVEL,
        median_report_seconds=median_seconds,
        high_severity_baseline_issues=len(high_issues),
        high_severity_missed=high_missed,
        high_severity_false_negative_rate=false_negative_rate,
        reviewer_coverage_threshold=REVIEWER_COVERAGE_THRESHOLD,
        rules=_rule_precisions(field_rows),
        reviewer_agreement=_reviewer_agreement(field_rows),
        calibration=_calibration(calibration_rows),
        calibration_findings=len(calibration_rows),
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
