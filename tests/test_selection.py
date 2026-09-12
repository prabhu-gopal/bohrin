"""Task selection: a prefix is a prefix, and a sample is reproducible.

The bound is part of every published rate, and until now it was always a prefix. These
tests pin the three properties an index row depends on: the sample is uniform, it is
redrawable from its seed alone, and asking for one where it cannot be drawn is refused
rather than silently served as a prefix.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from bohrin.adapters.selection import ALL, PREFIX, RANDOM, select_indices
from bohrin.probes.base import ProbeResult, ProbeStatus
from bohrin.report.model import Report
from bohrin.report.tty import render
from bohrin.scoring.gap import Coverage, GapScore


def test_no_bound_audits_everything() -> None:
    assert select_indices(500, None, None) == (None, ALL)
    assert select_indices(None, None, 7) == (None, ALL)


def test_a_bound_at_least_the_taskset_size_is_not_a_sample() -> None:
    """100 of 100 is the whole taskset, so it is reported as such, seed or no seed."""
    assert select_indices(100, 100, None) == (None, ALL)
    assert select_indices(100, 250, 7) == (None, ALL)


def test_without_a_seed_the_bound_is_still_a_prefix() -> None:
    """The default is unchanged: existing commands keep their existing meaning."""
    assert select_indices(3270, 100, None) == (None, PREFIX)


def test_a_sample_is_the_right_size_distinct_in_range_and_ordered() -> None:
    indices, mode = select_indices(3270, 100, 7)

    assert mode == RANDOM
    assert indices is not None
    assert len(indices) == len(set(indices)) == 100
    assert indices == sorted(indices)
    assert all(0 <= i < 3270 for i in indices)


def test_the_same_seed_redraws_the_same_sample() -> None:
    """An index row is only reproducible if its sample is."""
    assert select_indices(10_000, 50, 7) == select_indices(10_000, 50, 7)


def test_different_seeds_draw_different_samples() -> None:
    first, _ = select_indices(10_000, 50, 7)
    second, _ = select_indices(10_000, 50, 8)

    assert first != second


def test_a_sample_reaches_the_whole_taskset_not_just_the_front() -> None:
    """The defect that motivated this sat at position 11 of 3270. A prefix of 10 could
    never see it; a sample of 10 has to be able to land anywhere."""
    seen = set()
    for seed in range(200):
        indices, _ = select_indices(1000, 10, seed)
        assert indices is not None
        seen.update(indices)

    # With 2000 draws from 1000 positions, the front is not special.
    assert max(seen) > 900
    assert len([i for i in seen if i >= 500]) > 100


def _clean_report(mode: str | None, seed: int | None) -> Report:
    return Report(
        target="./envs/t",
        adapter="verifiers_legacy",
        gap=GapScore(score=0.0, coverage=Coverage(measured=("weak_oracle",), total=1)),
        results=(ProbeResult(probe_id="weak_oracle", status=ProbeStatus.OK, sub_score=0.0, tasks_probed=100),),
        tasks_total=100,
        corpus_total=3270,
        selection_mode=mode,
        selection_seed=seed,
    )


def _rendered(report: Report) -> str:
    buf = io.StringIO()
    render(report, Console(file=buf, width=200, no_color=True))
    return " ".join(buf.getvalue().split())


def test_a_sample_says_so_on_the_headline_and_a_prefix_still_says_prefix() -> None:
    """The two claims are different, so they may never print the same way."""
    sampled = _rendered(_clean_report(RANDOM, 7))
    prefixed = _rendered(_clean_report(PREFIX, None))

    assert "100 random of 3270 tasks (seed 7)" in sampled
    assert "100 of 3270 tasks" in prefixed
    assert "random" not in prefixed


def test_a_clean_sample_is_caveated_as_an_estimate_not_as_a_prefix() -> None:
    sampled = _rendered(_clean_report(RANDOM, 7))
    prefixed = _rendered(_clean_report(PREFIX, None))

    assert "drawn uniformly at random (seed 7)" in sampled
    assert "prefix rather than a sample" not in sampled
    # The prefix warning has to survive exactly as it was for an unsampled bound.
    assert "prefix rather than a sample" in prefixed


def test_the_report_serialises_how_its_tasks_were_chosen() -> None:
    """An index row without this cannot be read: it is what separates an estimate of the
    taskset from a statement about its first hundred tasks."""
    assert _clean_report(RANDOM, 7).to_dict()["selection"] == {"mode": "random", "seed": 7}
    assert _clean_report(PREFIX, None).to_dict()["selection"] == {"mode": "prefix", "seed": None}
    # An adapter that does not report selection claims nothing.
    assert _clean_report(None, None).to_dict()["selection"] == {"mode": None, "seed": None}


def test_a_sample_is_refused_when_the_length_is_unknown() -> None:
    """A taskset that will not say how long it is cannot be sampled from. Refusing is the
    contract: degrading to a prefix would publish a prefix rate under a sample's name."""
    with pytest.raises(ValueError, match="length"):
        select_indices(None, 100, 7)
