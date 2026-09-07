"""Wilson score intervals and Cohen's kappa for small-sample pilot evidence.

Two small statistics, vendored rather than taken from a dependency, because the pilot
summary has to run offline on a participant-controlled machine and neither is large
enough to justify a wheel.

Both exist to stop a number being published that the evidence does not support:

* **Wilson interval.** Two approvals out of two is not 100% precision, it is a sample of
  two. A bare point estimate invites reading it as the former. Wilson is used rather than
  the normal approximation because the normal approximation's interval at ``p = 1`` has
  zero width, which is the same defect in a different disguise.
* **Cohen's kappa.** Percent agreement between two reviewers who both label almost
  everything the same way is high by construction. Kappa removes the agreement expected
  from the marginals -- and is *undefined*, not zero and not one, when that expectation is
  total. This module returns ``None`` for that case and the caller says so in words.

The confidence level is a published claim, so it is a named literal here and pinned by a
test against its own literal. A property test cannot catch this: every property of an
interval holds just as well for the 68% quantile as for the 95% one, and an interval
labelled 95% that carries 1.0 is simply narrower and wrong.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import sqrt

# Phi^-1(0.975): the two-sided normal quantile for a 95% interval.
#
# Do not replace this with a `statistics.NormalDist().inv_cdf` call at import time without
# also keeping the literal: the point of writing it out is that the number a reader sees
# is the number the code uses, and that a test can compare the two.
CONFIDENCE_LEVEL = 0.95
Z_TWO_SIDED_95 = 1.959963984540054


@dataclass(frozen=True, slots=True)
class Interval:
    """A closed proportion interval, with the confidence level it was computed at."""

    low: float
    high: float
    confidence_level: float


def wilson_interval(
    successes: int, trials: int, *, z: float = Z_TWO_SIDED_95, level: float = CONFIDENCE_LEVEL
) -> Interval | None:
    """Return the Wilson score interval for ``successes`` of ``trials``, or None.

    ``None`` means the interval is not measurable because there is nothing to measure --
    zero trials. It never means zero width and never means ``[0, 1]``; a caller that
    renders ``None`` as a number is reintroducing the defect this returns ``None`` to
    avoid.
    """

    if trials < 0:
        raise ValueError("trials must not be negative")
    if not 0 <= successes <= trials:
        raise ValueError("successes must lie between zero and trials")
    if trials == 0:
        return None

    n = float(trials)
    p = successes / n
    z_squared = z * z
    denominator = 1.0 + z_squared / n
    centre = (p + z_squared / (2.0 * n)) / denominator
    spread = (z / denominator) * sqrt(p * (1.0 - p) / n + z_squared / (4.0 * n * n))
    return Interval(
        low=max(0.0, centre - spread),
        high=min(1.0, centre + spread),
        confidence_level=level,
    )


def proportion(successes: int, trials: int) -> float | None:
    """Exact proportion, or ``None`` when the denominator is zero."""

    if trials < 0:
        raise ValueError("trials must not be negative")
    if not 0 <= successes <= trials:
        raise ValueError("successes must lie between zero and trials")
    if trials == 0:
        return None
    return float(Fraction(successes, trials))


@dataclass(frozen=True, slots=True)
class Agreement:
    """Agreement between two raters over the same items.

    ``kappa is None`` carries ``kappa_undefined``, which is a fact about the labels and
    not a failure: when both raters used one identical category throughout, the agreement
    expected by chance is total, kappa's denominator is zero, and no value of kappa
    describes the data.
    """

    compared: int
    agreed: int
    percent_agreement: float | None
    kappa: float | None
    kappa_undefined: bool


def cohens_kappa(first: Sequence[str], second: Sequence[str]) -> Agreement:
    """Percent agreement and Cohen's kappa for two aligned label sequences.

    Arithmetic is exact (``Fraction``) up to the final conversion, so a hand computation
    and this function agree digit for digit rather than approximately.
    """

    if len(first) != len(second):
        raise ValueError("both raters must label the same number of items")
    total = len(first)
    if total == 0:
        return Agreement(
            compared=0, agreed=0, percent_agreement=None, kappa=None, kappa_undefined=False
        )

    agreed = sum(1 for a, b in zip(first, second, strict=True) if a == b)
    observed = Fraction(agreed, total)

    first_counts = Counter(first)
    second_counts = Counter(second)
    expected = sum(
        (
            Fraction(first_counts[label], total) * Fraction(second_counts[label], total)
            for label in set(first_counts) | set(second_counts)
        ),
        Fraction(0),
    )

    if expected == 1:
        return Agreement(
            compared=total,
            agreed=agreed,
            percent_agreement=float(observed),
            kappa=None,
            kappa_undefined=True,
        )
    return Agreement(
        compared=total,
        agreed=agreed,
        percent_agreement=float(observed),
        kappa=float((observed - expected) / (1 - expected)),
        kappa_undefined=False,
    )
