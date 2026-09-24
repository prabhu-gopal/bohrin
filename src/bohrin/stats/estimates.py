"""Standard errors, intervals and detectable differences for an evaluation's scores.

Arithmetic only: nothing here runs a grader, so nothing here can accuse one. The formulas are the
ones the evaluation-statistics literature recommends, cited where they are used:

* Miller, *Adding Error Bars to Evals* (2024, arXiv:2411.00640): the standard error of a mean
  score (eq. 1), the clustered standard error for questions that come in groups (eq. 4), paired
  differences between two models on the same questions (eq. 7), and the minimum detectable
  effect (eq. 10).
* Bowyer et al., *Don't Use the CLT in LLM Evals With Fewer Than a Few Hundred Datapoints* (2025,
  arXiv:2503.01747): for pass/fail scores the normal-approximation interval "catastrophically
  fails" on small evaluations, and the Wilson score interval keeps its coverage; so pass/fail
  scores get Wilson, and any other interval on fewer than a few hundred tasks says so.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from bohrin.scoring.interval import Z_95

#: The one-sided normal quantile for 80% power: a real difference of the minimum detectable size is
#: found four times in five.
Z_POWER_80 = 0.8416212335729143

#: Below this many tasks a normal-approximation interval is flagged as likely too narrow.
FEW_HUNDRED = 300


def mean(values: Sequence[float]) -> float:
    """The arithmetic mean. Raises ``ValueError`` on no values."""
    if not values:
        raise ValueError("the mean of no values is undefined")
    return math.fsum(values) / len(values)


def standard_error(values: Sequence[float], clusters: Sequence[str] | None = None) -> float:
    """The standard error of the mean of ``values``, clustered when ``clusters`` is given.

    Unclustered, it is Miller's eq. 1: the sample variance over ``n``. Clustered, eq. 4 adds the
    covariance of every pair of values in the same cluster, so related questions are not counted
    as independent evidence. One value per cluster gives exactly the unclustered answer.
    """
    n = len(values)
    if n < 2:
        return math.nan
    centre = mean(values)
    residuals = [value - centre for value in values]
    variance = math.fsum(r * r for r in residuals) / (n - 1)
    squared = variance / n
    if clusters is not None:
        if len(clusters) != n:
            raise ValueError("one cluster label is needed per value")
        sums: dict[str, float] = {}
        squares: dict[str, float] = {}
        for label, r in zip(clusters, residuals, strict=True):
            sums[label] = sums.get(label, 0.0) + r
            squares[label] = squares.get(label, 0.0) + r * r
        # sum over clusters of sum over pairs i != j of r_i * r_j == (sum r)^2 - sum r^2
        cross = math.fsum(sums[label] ** 2 - squares[label] for label in sums)
        squared += cross / (n * n)
    return math.sqrt(max(squared, 0.0))


def normal_interval(centre: float, error: float) -> tuple[float, float]:
    """The 95% interval ``centre ± 1.96 · error``."""
    return centre - Z_95 * error, centre + Z_95 * error


def detectable_difference(difference_error: float) -> float:
    """Miller's eq. 10: the smallest true difference found with 80% power at the 5% level.

    ``difference_error`` is the standard error of the difference between two models: paired, when
    both were scored on the same tasks.
    """
    return (Z_95 + Z_POWER_80) * difference_error


__all__ = [
    "FEW_HUNDRED",
    "Z_POWER_80",
    "detectable_difference",
    "mean",
    "normal_interval",
    "standard_error",
]
