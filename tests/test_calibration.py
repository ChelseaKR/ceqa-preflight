"""Synthetic calibration: what it measures, and the two figures it refuses to invent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ceqa_preflight.calibration import (
    CALIBRATION_SCHEMA_VERSION,
    DEFECT_RULES,
    FALSE_POSITIVE_RATE_REASON,
    REVIEWER_SECONDS_REASON,
    SyntheticCalibration,
    _count_package,
    _rate,
    _Tally,
    run_synthetic_calibration,
)
from ceqa_preflight.checker import check_package
from ceqa_preflight.manifest import load_manifest
from ceqa_preflight.models import FilingType
from ceqa_preflight.rule_registry import default_catalog
from ceqa_preflight.synth import SyntheticDefect, write_synthetic_package

COMMITTED_RECORD = Path(__file__).parent.parent / "evals" / "synthetic-calibration.json"


@pytest.fixture(scope="module")
def calibration() -> SyntheticCalibration:
    return run_synthetic_calibration()


# --- What the record must never say -------------------------------------


def test_a_false_positive_rate_is_absent_rather_than_zero(
    calibration: SyntheticCalibration,
) -> None:
    # The whole reason this module exists as something other than a pass/fail
    # test. A rate nobody measured and a rate measured to be zero are different
    # facts, and the second is the one a reader acts on.
    assert calibration.false_positive_rate is None
    payload = json.loads(calibration.model_dump_json())
    assert payload["false_positive_rate"] is None
    assert "81" in calibration.false_positive_rate_reason
    assert calibration.false_positive_rate_reason == FALSE_POSITIVE_RATE_REASON


def test_a_reviewer_time_figure_is_absent_rather_than_machine_time(
    calibration: SyntheticCalibration,
) -> None:
    assert calibration.reviewer_seconds_median is None
    assert json.loads(calibration.model_dump_json())["reviewer_seconds_median"] is None
    assert calibration.reviewer_seconds_reason == REVIEWER_SECONDS_REASON
    # No wall-clock field anywhere: an automated run's duration is a property of
    # the machine, and offering it beside a missing reviewer figure invites the
    # substitution this record refuses.
    assert not [field for field in SyntheticCalibration.model_fields if field.endswith("_seconds")]


def test_no_trials_gives_no_rate_but_zero_of_two_gives_zero() -> None:
    # The distinction the whole record turns on, at the one place it is computed.
    assert _rate(0, 0) == (None, None, None)
    rate, low, high = _rate(0, 2)
    assert rate == 0.0
    assert low == 0.0
    assert high is not None and 0.0 < high < 1.0


# --- What it does measure -----------------------------------------------


def test_every_seeded_defect_is_detected_across_the_corpus(
    calibration: SyntheticCalibration,
) -> None:
    # `undetermined_reads` is asserted first and separately. A PDF inspection
    # that times out routes its rule to a human, and folding that into "missed"
    # would report a degraded machine as a weaker ruleset. This was measured, not
    # anticipated: an early run of this suite on a loaded machine recorded 3 of 4
    # for one defect, and the run that produced it was a degraded read.
    assert calibration.undetermined_reads == 0, (
        "a rule could not read what it needed on a seeded package; this record was "
        "measured under a degraded read and should be measured again, not published"
    )
    assert calibration.detection
    for row in calibration.detection:
        assert row.seeded_packages > 0
        assert row.undetermined == 0
        assert row.detected == row.seeded_packages


def test_four_of_four_is_published_as_its_interval_not_as_one_hundred_percent(
    calibration: SyntheticCalibration,
) -> None:
    # A bare 1.0 invites reading a sample of four as certainty. The interval is
    # pinned to its literal, not to a property: every property of an interval
    # holds equally for the 68% one, and a 68% interval labelled 95% is simply
    # narrower and wrong.
    assert calibration.interval_confidence_level == 0.95
    row = next(row for row in calibration.detection if row.defect is SyntheticDefect.ENCRYPTED)
    assert row.seeded_packages == 4
    assert row.detection_rate == 1.0
    assert row.detection_interval_high == 1.0
    assert row.detection_interval_low == pytest.approx(0.5101091635, abs=1e-9)


def test_nothing_fired_on_a_package_that_seeded_nothing_for_it(
    calibration: SyntheticCalibration,
) -> None:
    assert calibration.control_packages == 2
    for row in calibration.unseeded_findings:
        assert row.packages_where_it_fired == 0


def test_the_corpus_is_the_distinct_packages_and_is_not_padded(
    calibration: SyntheticCalibration,
) -> None:
    # `synth` is deterministic, so generating a package twice adds a trial and no
    # information. 11 distinct packages per filing type: a control, nine
    # single-defect packages, and one with every defect at once.
    assert calibration.packages == 22
    assert calibration.filing_types == ["NOE", "NOD"]
    seeded_per_defect = {row.defect: row.seeded_packages for row in calibration.detection}
    assert set(seeded_per_defect.values()) == {4}


# --- What it does not exercise, said out loud ---------------------------


def test_the_rules_the_pilot_exists_to_activate_are_listed_as_unexercised(
    calibration: SyntheticCalibration,
) -> None:
    # The honest headline. The generator seeds no filing-specific defect, so a
    # record naming only the rules it exercised would read as a clean bill of
    # health for a ruleset it never touched.
    unexercised = {row.rule_id for row in calibration.unexercised_rules}
    filing_specific = {
        rule.id for rule in default_catalog().rules if rule.id.startswith(("NOD-", "NOE-"))
    }
    assert filing_specific
    assert filing_specific <= unexercised
    exercised = {row.rule_id for row in calibration.detection}
    assert not exercised & unexercised


def test_a_rule_that_did_not_run_gets_no_rate_rather_than_a_clean_one() -> None:
    # A rule excluded from the run fires zero times. Counting that as "never
    # fired spuriously" would hand a withdrawn or unselected rule a record it did
    # not earn, so its denominator stays at zero and its rate stays absent.
    without_experimental = run_synthetic_calibration(include_experimental=False)
    by_rule = {row.rule_id: row for row in without_experimental.unseeded_findings}
    filing_specific = [
        rule.id for rule in default_catalog().rules if rule.id.startswith(("NOD-", "NOE-"))
    ]
    assert filing_specific
    for rule_id in filing_specific:
        row = by_rule[rule_id]
        assert row.packages_without_this_defect == 0
        assert row.rate is None
        assert row.interval_low is None
        assert row.interval_high is None


def test_a_manual_only_rule_shows_why_its_zero_is_structural(
    calibration: SyntheticCalibration,
) -> None:
    # A rule whose only outcome is `manual` cannot reach warning or failure, so
    # its 0/n is a property of the rule, not evidence of restraint. The statuses
    # it was observed to produce are recorded so the two cannot be confused.
    by_rule = {row.rule_id: row for row in calibration.unseeded_findings}
    manual_only = [
        rule_id for rule_id, row in by_rule.items() if row.statuses_observed == ["manual"]
    ]
    assert manual_only, "the catalogue has manual-only rules; this pins that they are marked"
    for rule_id in manual_only:
        assert by_rule[rule_id].packages_where_it_fired == 0


# --- The mapping cannot silently shrink ---------------------------------


def test_every_seedable_defect_has_a_declared_owning_rule() -> None:
    # A defect with no mapping would simply drop out of the measured set, and the
    # detection rate would stay at 100% of a smaller corpus.
    assert set(DEFECT_RULES) == set(SyntheticDefect)


def test_every_owning_rule_exists_in_the_catalogue() -> None:
    catalogue = {rule.id for rule in default_catalog().rules}
    assert set(DEFECT_RULES.values()) <= catalogue


def test_the_calibration_schema_version_is_its_own_sequence(
    calibration: SyntheticCalibration,
) -> None:
    # Pinned to its literal, and kept apart from `report_schema_version`: the two
    # documents change for unrelated reasons and sharing a number would make one
    # of them lie about the other.
    assert CALIBRATION_SCHEMA_VERSION == "1.0"
    payload = json.loads(calibration.model_dump_json())
    assert payload["calibration_schema_version"] == "1.0"
    assert "report_schema_version" not in payload


# --- The published record cannot drift from the code --------------------


def test_the_committed_record_matches_a_fresh_measurement(
    calibration: SyntheticCalibration,
) -> None:
    # The record is published, so it must not be able to detach from the ruleset
    # it describes. Regenerate with:
    #   ceqa-preflight pilot calibrate --out evals/synthetic-calibration.json
    assert COMMITTED_RECORD.exists()
    assert calibration.undetermined_reads == 0, (
        "the fresh measurement was degraded, so a mismatch here says nothing about drift"
    )
    assert COMMITTED_RECORD.read_text(encoding="utf-8") == (
        calibration.model_dump_json(indent=2) + "\n"
    )


def test_the_committed_record_names_the_ruleset_it_measured(
    calibration: SyntheticCalibration,
) -> None:
    assert calibration.ruleset_version == default_catalog().catalog_version
    assert calibration.include_experimental is True


def test_a_single_filing_type_run_reports_only_that_filing_type() -> None:
    one = run_synthetic_calibration(
        filing_types=[FilingType.NOE], defects=[SyntheticDefect.SCANNED]
    )
    assert one.filing_types == ["NOE"]
    # A control and one seeded package; no all-defects package, because there is
    # only one defect and it would be the same package twice.
    assert one.packages == 2
    assert one.control_packages == 1
    assert [row.seeded_packages for row in one.detection] == [1]


# --- The two accounting rules no corpus run can exercise ----------------
#
# Both of these were found by a negative control that did not fire. The corpus
# is deterministic and healthy, so it never produces an undetermined read and
# never produces a finding for a rule that did not run -- which means the code
# handling those two cases had no test that could fail. These reach them
# directly.


def test_an_undetermined_owner_is_counted_apart_from_a_miss() -> None:
    # The case the loaded-machine run hit: the owning rule routed to a human
    # because its facts were unavailable. That is not a detection and it is not
    # a miss, and folding it into the second would publish a degraded read as a
    # weaker ruleset.
    tally = _Tally(
        detected={SyntheticDefect.SCANNED: 0},
        undetermined={SyntheticDefect.SCANNED: 0},
        seeded_packages={SyntheticDefect.SCANNED: 0},
        fired_without={"PDF-003": 0},
        packages_without={"PDF-003": 0},
        statuses_observed={},
        total_packages=0,
        control_packages=0,
    )
    _count_package(
        tally,
        {SyntheticDefect.SCANNED},
        fired=set(),
        statuses={"PDF-003": {"manual"}},
    )
    assert tally.seeded_packages[SyntheticDefect.SCANNED] == 1
    assert tally.detected[SyntheticDefect.SCANNED] == 0
    assert tally.undetermined[SyntheticDefect.SCANNED] == 1

    # And a genuine silence is still a miss, not an undetermined read.
    _count_package(
        tally,
        {SyntheticDefect.SCANNED},
        fired=set(),
        statuses={"PDF-003": {"pass"}},
    )
    assert tally.detected[SyntheticDefect.SCANNED] == 0
    assert tally.undetermined[SyntheticDefect.SCANNED] == 1


def test_a_rule_that_did_not_run_emits_no_finding_to_count(tmp_path: Path) -> None:
    # `_run_package` subtracts `not_run` rule ids before counting. A control
    # deleting that subtraction stayed green, because a skipped rule emits no
    # finding in the first place -- so the subtraction is belt and braces, and
    # this pins the brace: the report property it rests on. If a skipped rule
    # ever started emitting a finding, this fails here rather than silently
    # crediting it with a clean record.
    directory = tmp_path / "pkg"
    write_synthetic_package(directory, FilingType.NOE, [])
    manifest = load_manifest(directory / "package.yaml")
    report, _exit_code = check_package(
        directory, FilingType.NOE, manifest=manifest, include_experimental=False
    )
    skipped = {row.rule_id for row in report.not_run}
    assert skipped, "the fixture premise: experimental rules are skipped by default"
    reported = {finding.rule_id for finding in (*report.findings, *report.manual_review)}
    assert not skipped & reported
