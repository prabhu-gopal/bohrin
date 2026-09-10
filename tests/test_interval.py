"""The Wilson interval that every reported rate now carries.

Checked against published values rather than against the formula it implements — a test
that recomputes the same expression only proves the code agrees with itself.
"""

from __future__ import annotations

import pytest

from bohrin.scoring.interval import rate, wilson_interval


@pytest.mark.parametrize(
    ("affected", "measured", "low", "high"),
    [
        (0, 10, 0.0, 0.2775),
        (5, 10, 0.2366, 0.7634),
        (10, 10, 0.7225, 1.0),
        (2, 2, 0.3424, 1.0),
        (1, 20, 0.0089, 0.2361),
    ],
)
def test_matches_published_wilson_values(affected: int, measured: int, low: float, high: float) -> None:
    interval = wilson_interval(affected, measured)
    assert interval is not None
    assert interval[0] == pytest.approx(low, abs=5e-4)
    assert interval[1] == pytest.approx(high, abs=5e-4)


def test_two_of_two_is_not_certainty() -> None:
    """The case the textbook interval gets worst, and the one a small audit produces most.
    ``p ± z·√(p(1−p)/n)`` gives ``[1, 1]`` here — certainty from two observations."""
    low, high = wilson_interval(2, 2) or (1.0, 1.0)
    assert low < 0.5 < high


def test_nothing_measured_has_no_interval() -> None:
    assert wilson_interval(0, 0) is None
    assert rate(0, 0)["interval_95"] is None


@pytest.mark.parametrize(("affected", "measured"), [(-1, 5), (6, 5)])
def test_impossible_counts_are_refused(affected: int, measured: int) -> None:
    with pytest.raises(ValueError):
        wilson_interval(affected, measured)


def test_the_interval_narrows_as_the_sample_grows() -> None:
    widths = []
    for measured in (4, 40, 400):
        low, high = wilson_interval(measured // 2, measured) or (0.0, 1.0)
        widths.append(high - low)
    assert widths == sorted(widths, reverse=True)


def test_every_interval_contains_its_own_rate_and_stays_in_bounds() -> None:
    for measured in range(1, 30):
        for affected in range(measured + 1):
            low, high = wilson_interval(affected, measured) or (0.0, 1.0)
            assert 0.0 <= low <= affected / measured <= high <= 1.0
