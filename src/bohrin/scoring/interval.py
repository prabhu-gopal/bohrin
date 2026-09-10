"""How much a proportion of tasks is worth, given how many tasks are under it.

Every sub-score is a count of tasks over a count of tasks, and the second count carries as
much of the claim as the first. ``2 of 2`` and ``300 of 300`` both read as "every task";
the first is a lead and the second is a measurement. A rate reported without its sample is
the malformed-number problem the Verification Gap already forbids for probes, one level
down — and it is not hypothetical: a synthetic environment in which ``weak_oracle`` could
measure only 2 of 20 tasks produced ``VERIFICATION GAP: 50 / 100`` at full probe coverage,
with nothing on the line to say what it rested on.

**Why Wilson, and not the textbook interval.** ``p ± z·√(p(1−p)/n)`` fails exactly where an
audit's samples live: small ``n``, and ``p`` at or near 0 or 1 — which is where a clean or a
fully compromised verifier puts it. At ``2 of 2`` it collapses to ``[1, 1]``, claiming
certainty from two observations. Brown, Cai and DasGupta's comparison of nine methods
(*Statistical Science*, 2001) recommended the Wilson score interval for small samples, and
recent guidance on evaluating agents over small task sets makes the same recommendation,
with uncertainty reported per task set rather than only in aggregate.

**What it does not describe.** Sampling uncertainty only. It says nothing about whether the
operators could construct the relevant payload at all; that limit is qualitative, and the
clean-result caveat states it separately.
"""

from __future__ import annotations

import math

#: The two-sided 95% normal quantile.
Z_95 = 1.959963984540054


def wilson_interval(affected: int, measured: int, z: float = Z_95) -> tuple[float, float] | None:
    """The Wilson score interval for ``affected`` of ``measured``, or None when nothing was
    measured — an interval over zero observations is not a narrow one, it is not one."""
    if measured <= 0:
        return None
    if not 0 <= affected <= measured:
        raise ValueError(f"affected={affected} is outside 0..measured={measured}")
    p = affected / measured
    z2 = z * z
    denominator = 1.0 + z2 / measured
    centre = (p + z2 / (2 * measured)) / denominator
    half = z * math.sqrt(p * (1.0 - p) / measured + z2 / (4 * measured * measured)) / denominator
    # At the extremes the Wilson bound is exactly 0 or exactly 1 -- the algebra cancels --
    # but floating point lands a hair either side. Measured over every extreme with n < 200,
    # the clamp alone failed to contain the rate in 95 of 398 cases: `10 of 10` gave a high
    # of 0.9999999999999999, and `0 of 3` a low of 5.6e-17. The property test caught it;
    # rounding to four places in the JSON would have hidden it. So the exact values are set
    # rather than computed, and the clamp covers the rest.
    low = 0.0 if affected == 0 else max(0.0, centre - half)
    high = 1.0 if affected == measured else min(1.0, centre + half)
    return low, high


def rate(affected: int, measured: int) -> dict[str, object]:
    """A proportion in the shape every probe reports it: the counts, and the interval.

    This is the ``detail.rate`` object in ``--json`` (report schema 1.3).
    """
    interval = wilson_interval(affected, measured)
    return {
        "affected": affected,
        "measured": measured,
        "interval_95": [round(interval[0], 4), round(interval[1], 4)] if interval else None,
    }


__all__ = ["Z_95", "rate", "wilson_interval"]
