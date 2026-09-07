"""Tests for the vendored Wilson interval and Cohen's kappa.

Every published figure here is pinned to a literal computed by hand, not to a property.
A property test cannot catch a wrong constant: "the interval contains the point estimate"
and "the interval lies in [0, 1]" hold exactly as well for the 68% quantile as for the
95% one, so an interval labelled 95% that carried 1.0 would pass every property and be
narrower than the truth by a third.
"""

from __future__ import annotations

from fractions import Fraction
from math import isclose

import pytest

from ceqa_preflight.intervals import (
    CONFIDENCE_LEVEL,
    Z_TWO_SIDED_95,
    cohens_kappa,
    proportion,
    wilson_interval,
)


def test_the_confidence_level_and_its_quantile_are_the_pair_they_claim_to_be() -> None:
    """The one assertion that stops a 95% label sitting on a 68% interval.

    `NormalDist` is used only here, as an independent check of the literal the module
    ships; the module keeps the literal so a reader sees the number the code uses.
    """

    from statistics import NormalDist

    assert CONFIDENCE_LEVEL == 0.95
    assert Z_TWO_SIDED_95 == 1.959963984540054
    assert isclose(
        Z_TWO_SIDED_95,
        NormalDist().inv_cdf(1 - (1 - CONFIDENCE_LEVEL) / 2),
        rel_tol=1e-12,
    )


def test_two_of_two_is_reported_as_an_interval_that_reaches_down_to_a_third() -> None:
    """Hand computation, so the digits are checked and not merely the shape.

    p = 1, n = 2, z = 1.959963984540054:
        centre = (1 + z**2/4) / (1 + z**2/2)      = 0.6711901...
        spread = z / (1 + z**2/2) * sqrt(z**2/16) = 0.3288098...

    The point of the assertion is the lower bound. Two of two is not 100% precision with
    certainty; it is consistent with a true rate as low as about 34%.
    """

    interval = wilson_interval(2, 2)

    assert interval is not None
    assert interval.confidence_level == 0.95
    assert isclose(interval.low, 0.34238022750665303, rel_tol=1e-12)
    assert interval.high == 1.0


def test_nine_of_ten_carries_the_published_wilson_bounds() -> None:
    interval = wilson_interval(9, 10)

    assert interval is not None
    assert isclose(interval.low, 0.5958499732047615, rel_tol=1e-12)
    assert isclose(interval.high, 0.9821237869049271, rel_tol=1e-12)


def test_zero_trials_has_no_interval_rather_than_a_zero_one() -> None:
    assert wilson_interval(0, 0) is None
    assert proportion(0, 0) is None


def test_zero_successes_of_a_real_sample_is_still_an_interval() -> None:
    interval = wilson_interval(0, 5)

    assert interval is not None
    assert interval.low == 0.0
    assert interval.high > 0.0, "an interval from five observations is not a point at zero"


def test_impossible_counts_are_refused_rather_than_clamped() -> None:
    with pytest.raises(ValueError, match="between zero and trials"):
        wilson_interval(3, 2)
    with pytest.raises(ValueError, match="must not be negative"):
        wilson_interval(0, -1)
    with pytest.raises(ValueError, match="between zero and trials"):
        proportion(3, 2)


def test_kappa_matches_a_hand_computation_for_one_disagreement_in_ten() -> None:
    """Rater A: 8 true_positive, 2 false_positive. Rater B: 9 true_positive, 1 false_positive.

    observed = 9/10
    expected = (8/10)(9/10) + (2/10)(1/10) = 74/100
    kappa    = (90/100 - 74/100) / (1 - 74/100) = 16/26 = 8/13
    """

    first = ["true_positive"] * 8 + ["false_positive", "false_positive"]
    second = ["true_positive"] * 8 + ["true_positive", "false_positive"]

    agreement = cohens_kappa(first, second)

    assert agreement.compared == 10
    assert agreement.agreed == 9
    assert agreement.percent_agreement == 0.9
    assert agreement.kappa == float(Fraction(8, 13))
    assert agreement.kappa == 0.6153846153846154
    assert agreement.kappa_undefined is False


def test_total_chance_agreement_leaves_kappa_undefined_not_perfect() -> None:
    labels = ["true_positive"] * 4

    agreement = cohens_kappa(labels, labels)

    assert agreement.percent_agreement == 1.0
    assert agreement.kappa is None, "kappa's denominator is zero here; it is not 1.0"
    assert agreement.kappa_undefined is True


def test_total_disagreement_on_balanced_marginals_is_a_kappa_of_minus_one() -> None:
    """observed = 0; expected = (1/2)(1/2) + (1/2)(1/2) = 1/2; kappa = -1/2 / 1/2 = -1."""

    agreement = cohens_kappa(
        ["true_positive", "false_positive"], ["false_positive", "true_positive"]
    )

    assert agreement.agreed == 0
    assert agreement.percent_agreement == 0.0
    assert agreement.kappa == -1.0


def test_opposite_single_labels_give_a_kappa_of_zero_not_minus_one() -> None:
    """One rater says true_positive throughout and the other false_positive throughout.

    Chance agreement is zero here, not total, so kappa is defined and equals the observed
    agreement of zero. Worth pinning because it is easy to assume every total
    disagreement is -1.
    """

    agreement = cohens_kappa(["true_positive"] * 2, ["false_positive"] * 2)

    assert agreement.kappa == 0.0
    assert agreement.kappa_undefined is False


def test_no_compared_items_yields_no_agreement_figure() -> None:
    agreement = cohens_kappa([], [])

    assert agreement.compared == 0
    assert agreement.percent_agreement is None
    assert agreement.kappa is None
    assert agreement.kappa_undefined is False


def test_misaligned_label_sequences_are_refused() -> None:
    with pytest.raises(ValueError, match="same number of items"):
        cohens_kappa(["true_positive"], [])
