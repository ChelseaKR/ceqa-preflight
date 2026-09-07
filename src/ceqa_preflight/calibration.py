"""Measuring the built-in rules against the synthetic generator's seeded defects.

This is the half of the pilot false-positive question that needs no reviewer, no
permission and no real filing: `synth` seeds objective, named defects, so whether
the rule that owns each defect fires is a fact the machine can establish alone.

What this measures, precisely
-----------------------------
For every seeded defect, whether its owning rule reached ``warning`` or
``failure`` on a package that contains it -- a *detection rate against the
generator's notion of a defect*. And, on packages seeded with nothing, how often
any rule fires at all -- an *unseeded-finding rate*.

What this does not measure, and must never be read as
-----------------------------------------------------
**A false-positive rate.** That is a rate against real filings, and it requires
qualified CEQA reviewers labelling real findings; that is issue #81. A finding on
a synthetic package that the generator did not seed is not necessarily wrong --
it may be a correct observation about the generator's own output -- so counting
those as false positives would publish a number with no referent. Both figures
this module cannot support are carried as ``None`` with a written reason, never
as ``0.0``: a rate nobody measured and a rate measured to be zero are different
facts, and rendering the first as the second is the defect this repository takes
most seriously.

**A reviewer-time figure.** Nobody reviewed these packages. The wall clock of an
automated run is a property of the machine that ran it, not of a reviewer, and
it is deliberately absent from the record rather than offered as a stand-in.

Why the sample is small, and why it is not padded
-------------------------------------------------
`synth` is deterministic: one defect and one filing type produce one package,
byte for byte, every time. Generating it a hundred times would raise the
denominator without adding a single independent observation, which is
manufacturing a sample rather than measuring one. So the corpus is exactly the
distinct packages available -- each defect alone, and every defect at once, for
each filing type -- and the resulting rates carry Wilson intervals that show how
little they rest on. Four of four is reported as its interval, not as 100%.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import Field

from ceqa_preflight.checker import check_package
from ceqa_preflight.intervals import CONFIDENCE_LEVEL, wilson_interval
from ceqa_preflight.manifest import load_manifest
from ceqa_preflight.models import FilingType, FindingStatus, StrictModel
from ceqa_preflight.rule_catalog import RuleDefinition
from ceqa_preflight.rule_registry import default_catalog
from ceqa_preflight.synth import SyntheticDefect, write_synthetic_package

#: Schema version for the calibration record only. Deliberately its own field and
#: its own sequence, not `report_schema_version`: an inspection report and a
#: calibration record change for unrelated reasons, and sharing a version would
#: make one of them lie about the other.
CALIBRATION_SCHEMA_VERSION = "1.0"

#: The confidence level every interval here is computed at, re-exported so a
#: reader of this module does not have to follow the import to learn it.
INTERVAL_CONFIDENCE_LEVEL = CONFIDENCE_LEVEL

#: Which rule owns each seedable defect.
#:
#: Written out rather than discovered by watching what fires, because a mapping
#: derived from the run cannot fail: if a defect stopped being detected, a
#: derived mapping would simply record that the defect now belongs to no rule and
#: the detection rate would stay at 100% of a smaller set. Stated here, the same
#: change shows up as a rule that missed.
DEFECT_RULES: dict[SyntheticDefect, str] = {
    SyntheticDefect.ENCRYPTED: "PDF-002",
    SyntheticDefect.UNREADABLE: "PDF-002",
    SyntheticDefect.SCANNED: "PDF-003",
    SyntheticDefect.FILLABLE_FORM: "PDF-007",
    SyntheticDefect.DUPLICATE: "FILE-002",
    SyntheticDefect.NON_PDF: "FILE-003",
    SyntheticDefect.BAD_SIGNATURE: "PDF-001",
    SyntheticDefect.WEAK_FILENAME: "FILE-001",
    SyntheticDefect.MISSING_MANIFEST_REFERENCE: "MAN-001",
}

#: The statuses that count as a rule having fired. `manual` is not one: a rule
#: that routes a package to a human has not detected anything on its own.
_FIRED = frozenset({FindingStatus.WARNING, FindingStatus.FAILURE})

FALSE_POSITIVE_RATE_REASON = (
    "not measurable here: a false-positive rate is a rate against real filings and "
    "needs qualified CEQA reviewers labelling real findings (issue #81). A finding on "
    "a synthetic package that the generator did not seed is not thereby wrong, so the "
    "unseeded-finding rate below is not a substitute for it."
)

REVIEWER_SECONDS_REASON = (
    "not measurable here: no reviewer labelled these packages. The wall clock of an "
    "automated run is a property of the machine that ran it and is not recorded as a "
    "stand-in for reviewer time."
)


class DefectDetection(StrictModel):
    """Whether the rule that owns one seeded defect fired on packages holding it.

    ``detection_rate`` and its interval bounds are ``None`` together, and only
    when ``seeded_packages`` is zero -- a defect nobody seeded has no detection
    rate, which is not a detection rate of zero.
    """

    defect: SyntheticDefect
    rule_id: str
    seeded_packages: int = Field(ge=0)
    detected: int = Field(ge=0)
    #: Seeded packages where the owning rule came back undetermined -- routed to a
    #: human because the facts it needs were unavailable -- rather than firing or
    #: staying silent. A PDF inspection that times out or whose worker never
    #: answers lands here, and it is counted apart from a miss on purpose: a rule
    #: that could not read the file has not failed to detect anything, and
    #: folding the two together would publish a degraded run as a lower detection
    #: rate. Any non-zero value means this record was measured under a degraded
    #: read and should be measured again, not published.
    undetermined: int = Field(ge=0, default=0)
    detection_rate: float | None = Field(default=None, ge=0, le=1)
    detection_interval_low: float | None = Field(default=None, ge=0, le=1)
    detection_interval_high: float | None = Field(default=None, ge=0, le=1)


class UnseededFindings(StrictModel):
    """How often one rule fired on a package with nothing seeded for it.

    Named for what it is. These are *not* false positives: the generator's own
    output is not a filing, and a finding it did not intend may still be a
    correct observation. The number is here so a rule that fires on everything
    is visible, not so it can be published as an error rate.
    """

    rule_id: str
    packages_without_this_defect: int = Field(ge=0)
    packages_where_it_fired: int = Field(ge=0)
    rate: float | None = Field(default=None, ge=0, le=1)
    interval_low: float | None = Field(default=None, ge=0, le=1)
    interval_high: float | None = Field(default=None, ge=0, le=1)
    #: Every status this rule was observed to produce across the corpus. Recorded
    #: because a rule that only ever returns ``manual`` cannot reach ``warning``
    #: or ``failure`` at all, so its zero is structural rather than evidence of
    #: restraint -- a rate that cannot be anything but zero, printed beside rates
    #: that could have been.
    statuses_observed: list[str] = Field(default_factory=list)


class UnexercisedRule(StrictModel):
    """A rule in the catalogue that no synthetic defect targets.

    Listed rather than omitted. A calibration record that names only the rules it
    exercised cannot be told apart from one that exercised everything, and the
    filing-specific rules the pilot exists to activate are exactly the ones the
    generator seeds nothing for.
    """

    rule_id: str
    filing_types: list[str]


class SyntheticCalibration(StrictModel):
    """The whole synthetic calibration record: what was measured and what was not."""

    calibration_schema_version: str = CALIBRATION_SCHEMA_VERSION
    ruleset_version: str = Field(min_length=1)
    include_experimental: bool
    filing_types: list[str]
    packages: int = Field(ge=0)
    control_packages: int = Field(ge=0)
    interval_confidence_level: float = Field(gt=0, lt=1)
    detection: list[DefectDetection]
    unseeded_findings: list[UnseededFindings]
    unexercised_rules: list[UnexercisedRule]
    #: Seeded packages, across every defect, whose owning rule could not read
    #: what it needed. Zero in a record worth publishing. See
    #: :attr:`DefectDetection.undetermined`.
    undetermined_reads: int = Field(ge=0, default=0)
    #: Always ``None``. Kept as a field, with its reason beside it, so that a
    #: consumer looking for a false-positive rate finds the explicit absence
    #: rather than reaching for the nearest number that looks like one.
    false_positive_rate: float | None = None
    false_positive_rate_reason: str = FALSE_POSITIVE_RATE_REASON
    reviewer_seconds_median: float | None = None
    reviewer_seconds_reason: str = REVIEWER_SECONDS_REASON


def _rate(successes: int, trials: int) -> tuple[float | None, float | None, float | None]:
    """A proportion and its Wilson bounds, or three ``None`` when there are no trials."""

    interval = wilson_interval(successes, trials)
    if interval is None:
        return None, None, None
    return successes / trials, interval.low, interval.high


def _run_package(
    directory: Path, filing_type: FilingType, *, include_experimental: bool
) -> tuple[set[str], dict[str, set[str]]]:
    """Rule ids that fired on one package, and every status each rule that ran produced.

    Both, because a rule that did not run fires zero times, and counting that as
    "never fired spuriously" would credit a withdrawn or unselected rule with a
    clean record it did not earn. Only rules that ran enter the denominator.
    """

    manifest = load_manifest(directory / "package.yaml")
    report, _exit_code = check_package(
        directory,
        filing_type,
        manifest=manifest,
        include_experimental=include_experimental,
    )
    # Belt and braces. A skipped rule emits no finding at all, so this
    # subtraction currently removes nothing -- a control deleting it stayed
    # green. The report property it rests on is pinned by a test instead, so a
    # change that made a skipped rule report would fail there rather than
    # crediting it here with a clean record it did not earn.
    skipped = {skipped_check.rule_id for skipped_check in report.not_run}
    statuses: dict[str, set[str]] = {}
    for finding in (*report.findings, *report.manual_review):
        if finding.rule_id in skipped:
            continue
        statuses.setdefault(finding.rule_id, set()).add(finding.status.value)
    fired = {
        rule_id for rule_id, seen in statuses.items() if seen & {status.value for status in _FIRED}
    }
    return fired, statuses


def _corpus(defects: Sequence[SyntheticDefect]) -> list[tuple[str, tuple[SyntheticDefect, ...]]]:
    """The distinct synthetic packages worth generating, per filing type.

    Each defect alone isolates its rule; every defect at once catches one defect
    masking another. `synth` is deterministic, so nothing is gained by asking for
    either package twice and the corpus does not pretend otherwise.
    """

    cases: list[tuple[str, tuple[SyntheticDefect, ...]]] = [("control", ())]
    cases.extend((defect.value, (defect,)) for defect in defects)
    if len(defects) > 1:
        cases.append(("all-defects", tuple(defects)))
    return cases


@dataclass
class _Tally:
    """Raw counts from walking the corpus, before any rate is computed."""

    detected: dict[SyntheticDefect, int]
    undetermined: dict[SyntheticDefect, int]
    seeded_packages: dict[SyntheticDefect, int]
    fired_without: dict[str, int]
    packages_without: dict[str, int]
    statuses_observed: dict[str, set[str]]
    total_packages: int
    control_packages: int


def _tally_corpus(
    filing_types: list[FilingType],
    seeded: list[SyntheticDefect],
    catalog_rules: Mapping[str, RuleDefinition],
    *,
    include_experimental: bool,
) -> _Tally:
    """Generate every package in the corpus and count what each rule did."""

    tally = _Tally(
        detected=dict.fromkeys(seeded, 0),
        undetermined=dict.fromkeys(seeded, 0),
        seeded_packages=dict.fromkeys(seeded, 0),
        fired_without=dict.fromkeys(catalog_rules, 0),
        packages_without=dict.fromkeys(catalog_rules, 0),
        statuses_observed={},
        total_packages=0,
        control_packages=0,
    )
    for filing_type in filing_types:
        for label, case_defects in _corpus(seeded):
            with TemporaryDirectory() as scratch:
                directory = Path(scratch) / f"{filing_type.value}-{label}"
                write_synthetic_package(directory, filing_type, list(case_defects))
                fired, statuses = _run_package(
                    directory, filing_type, include_experimental=include_experimental
                )
            tally.total_packages += 1
            if not case_defects:
                tally.control_packages += 1
            _count_package(tally, set(case_defects), fired, statuses)
    return tally


def _count_package(
    tally: _Tally,
    present: set[SyntheticDefect],
    fired: set[str],
    statuses: dict[str, set[str]],
) -> None:
    """Fold one package's result into the running counts."""

    for defect in present:
        tally.seeded_packages[defect] += 1
        owner = DEFECT_RULES[defect]
        if owner in fired:
            tally.detected[defect] += 1
        elif FindingStatus.MANUAL.value in statuses.get(owner, set()):
            tally.undetermined[defect] += 1
    # A rule is "without its defect" on this package when nothing seeded here
    # targets it. That is the only population in which its firing is unexplained
    # by the seed.
    targeted = {DEFECT_RULES[defect] for defect in present}
    for rule_id, seen in statuses.items():
        tally.statuses_observed.setdefault(rule_id, set()).update(seen)
        if rule_id in targeted:
            continue
        tally.packages_without[rule_id] += 1
        if rule_id in fired:
            tally.fired_without[rule_id] += 1


def run_synthetic_calibration(
    *,
    filing_types: Iterable[FilingType] = (FilingType.NOE, FilingType.NOD),
    defects: Sequence[SyntheticDefect] | None = None,
    include_experimental: bool = True,
) -> SyntheticCalibration:
    """Generate the synthetic corpus, check it, and report what that establishes.

    ``include_experimental`` defaults to true because the filing-specific rules
    are the ones the pilot exists to activate; they appear in
    ``unexercised_rules`` because the generator seeds no defect for them.
    """

    seeded = list(defects) if defects is not None else list(SyntheticDefect)
    ordered_types = list(filing_types)
    catalog_rules = {rule.id: rule for rule in default_catalog().rules}
    tally = _tally_corpus(
        ordered_types,
        seeded,
        catalog_rules,
        include_experimental=include_experimental,
    )
    detected = tally.detected
    seeded_packages = tally.seeded_packages
    fired_without = tally.fired_without
    packages_without = tally.packages_without
    statuses_observed = tally.statuses_observed
    total_packages = tally.total_packages
    control_packages = tally.control_packages

    detection: list[DefectDetection] = []
    for defect in seeded:
        rate, low, high = _rate(detected[defect], seeded_packages[defect])
        detection.append(
            DefectDetection(
                defect=defect,
                rule_id=DEFECT_RULES[defect],
                seeded_packages=seeded_packages[defect],
                detected=detected[defect],
                undetermined=tally.undetermined[defect],
                detection_rate=rate,
                detection_interval_low=low,
                detection_interval_high=high,
            )
        )

    unseeded: list[UnseededFindings] = []
    for rule_id in sorted(catalog_rules):
        rate, low, high = _rate(fired_without[rule_id], packages_without[rule_id])
        unseeded.append(
            UnseededFindings(
                rule_id=rule_id,
                packages_without_this_defect=packages_without[rule_id],
                packages_where_it_fired=fired_without[rule_id],
                rate=rate,
                interval_low=low,
                interval_high=high,
                statuses_observed=sorted(statuses_observed.get(rule_id, set())),
            )
        )

    exercised = {DEFECT_RULES[defect] for defect in seeded}
    unexercised = [
        UnexercisedRule(
            rule_id=rule_id,
            filing_types=sorted(str(value) for value in catalog_rules[rule_id].filing_types),
        )
        for rule_id in sorted(catalog_rules)
        if rule_id not in exercised
    ]

    return SyntheticCalibration(
        ruleset_version=default_catalog().catalog_version,
        include_experimental=include_experimental,
        filing_types=[filing_type.value for filing_type in ordered_types],
        packages=total_packages,
        control_packages=control_packages,
        interval_confidence_level=INTERVAL_CONFIDENCE_LEVEL,
        detection=detection,
        unseeded_findings=unseeded,
        unexercised_rules=unexercised,
        undetermined_reads=sum(tally.undetermined.values()),
    )
