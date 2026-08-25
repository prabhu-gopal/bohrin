"""The trajectory working set: bounded in bytes, and a *sample* rather than a prefix.

Two properties, each closing a measured defect in the engine's old `reservoir[:5000]`:

1. **A byte budget.** A count cap says nothing about memory, because an episode costs
   ``T × D × 8`` per channel. Measured on the old cap: ``T=5000, D=32`` admitted **12.8 GB**.
2. **Uniform sampling.** Keeping the *first* N episodes biases the working set toward the start
   of collection. That is not a cosmetic bias: `stats.distribution_drift` compares the first
   half of the reservoir against the second to find mid-collection shifts, so on any dataset
   larger than the cap it compared the first quarter against the second and called that the
   whole collection — a drift introduced late was structurally invisible.
"""

from __future__ import annotations

import numpy as np
import pytest

import _synth
from bohrin.ir.episode import Episode
from bohrin.profile.episode_reservoir import EpisodeReservoir, episode_nbytes


def _episode(index: int, *, length: int = 40, dim: int = 6) -> Episode:
    rng = np.random.default_rng(index)
    action = rng.normal(size=(length, dim))
    return _synth._episode(index, action, _synth.integrate(action))


def _fill(reservoir: EpisodeReservoir, n: int, **kwargs: int) -> None:
    for i in range(n):
        reservoir.add(_episode(i, **kwargs))


def _rng() -> np.random.Generator:
    return np.random.default_rng(0)


# ------------------------------------------------------------------------ byte budget


def test_the_byte_budget_is_respected() -> None:
    one = episode_nbytes(_episode(0))
    budget = one * 10
    reservoir = EpisodeReservoir(capacity=10_000, budget_bytes=budget, rng=_rng())
    _fill(reservoir, 500)
    assert reservoir.nbytes <= budget
    assert len(reservoir.episodes) <= 10


def test_a_huge_episode_count_cannot_blow_memory() -> None:
    """The scenario that measured 12.8 GB: many long, wide episodes under a small budget."""
    budget = 8 * 1024 * 1024
    reservoir = EpisodeReservoir(capacity=5000, budget_bytes=budget, rng=_rng())
    _fill(reservoir, 300, length=2000, dim=32)
    assert reservoir.nbytes <= budget
    assert reservoir.truncated
    assert reservoir.dropped_for_memory > 0


def test_the_count_cap_still_applies_under_a_generous_budget() -> None:
    reservoir = EpisodeReservoir(capacity=7, budget_bytes=1 << 30, rng=_rng())
    _fill(reservoir, 200)
    assert len(reservoir.episodes) == 7
    assert reservoir.seen == 200


def test_a_single_oversized_episode_is_still_kept() -> None:
    """An empty working set would disable half the battery; one over-budget episode is better."""
    reservoir = EpisodeReservoir(capacity=10, budget_bytes=16, rng=_rng())
    reservoir.add(_episode(0, length=500, dim=32))
    assert len(reservoir.episodes) == 1


def test_episode_nbytes_counts_the_retained_columns() -> None:
    episode = _episode(0, length=40, dim=6)
    # action + proprio (40×6 float64 each) + timestamps (40 float64).
    assert episode_nbytes(episode) == 40 * 6 * 8 * 2 + 40 * 8


def test_lazy_images_are_not_charged_to_the_budget() -> None:
    """Frames are file handles until a detector asks; charging them would refuse video data."""
    plain = _synth.clean_dataset(n_episodes=1)[0]
    with_video = _synth.vision_dataset(n_episodes=1, length=plain.length)[0]
    assert episode_nbytes(with_video) < episode_nbytes(plain) * 50


# --------------------------------------------------------------------- uniform sampling


def test_the_retained_set_is_not_a_prefix() -> None:
    """The bug: `reservoir[:cap]` kept only the earliest episodes of a longer stream."""
    reservoir = EpisodeReservoir(capacity=20, budget_bytes=1 << 30, rng=_rng())
    _fill(reservoir, 400)
    kept = [int(ep.episode_id[2:]) for ep in reservoir.episodes]
    assert len(kept) == 20
    assert max(kept) > 200, f"retained only early episodes: {sorted(kept)}"


def test_late_episodes_are_retained_about_as_often_as_early_ones() -> None:
    """Uniformity, measured: the second half of the stream must be ~half the sample.

    This is the property `stats.distribution_drift` depends on — it can only see a shift that
    happens late if late episodes actually reach the working set.
    """
    total, capacity, trials = 400, 40, 60
    late_fraction = []
    for seed in range(trials):
        reservoir = EpisodeReservoir(capacity=capacity, budget_bytes=1 << 30, rng=np.random.default_rng(seed))
        _fill(reservoir, total)
        kept = [int(ep.episode_id[2:]) for ep in reservoir.episodes]
        late_fraction.append(sum(1 for k in kept if k >= total // 2) / len(kept))
    mean_late = float(np.mean(late_fraction))
    assert 0.40 <= mean_late <= 0.60, f"second half made up {mean_late:.2%} of the sample, expected ~50%"


def test_sampling_is_reproducible_under_a_seed() -> None:
    def run() -> list[str]:
        reservoir = EpisodeReservoir(capacity=15, budget_bytes=1 << 30, rng=np.random.default_rng(7))
        _fill(reservoir, 200)
        return [ep.episode_id for ep in reservoir.episodes]

    assert run() == run()


def test_different_seeds_choose_differently() -> None:
    def run(seed: int) -> list[str]:
        reservoir = EpisodeReservoir(capacity=15, budget_bytes=1 << 30, rng=np.random.default_rng(seed))
        _fill(reservoir, 200)
        return [ep.episode_id for ep in reservoir.episodes]

    assert run(1) != run(2)


def test_a_short_stream_is_kept_whole() -> None:
    reservoir = EpisodeReservoir(capacity=50, budget_bytes=1 << 30, rng=_rng())
    _fill(reservoir, 12)
    assert len(reservoir.episodes) == 12
    assert not reservoir.truncated
    assert reservoir.dropped_for_memory == 0


@pytest.mark.parametrize(("capacity", "budget"), [(0, 1024), (10, 0), (-1, 1024)])
def test_degenerate_bounds_are_refused(capacity: int, budget: int) -> None:
    with pytest.raises(ValueError):
        EpisodeReservoir(capacity=capacity, budget_bytes=budget, rng=_rng())


# ------------------------------------------------------------------------- end to end


def test_a_scan_honours_the_memory_budget() -> None:
    from bohrin.api import scan

    path = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=40))
    # A budget of 1 MiB still admits plenty of these small episodes, and the scan must work.
    report = scan(path, max_episode_memory_mb=1)
    assert report.dataset.n_episodes == 40


def test_a_tiny_budget_degrades_gracefully_rather_than_failing() -> None:
    """Exceeding the budget costs statistical power, never correctness."""
    from bohrin.api import scan

    path = _synth.register_memory_dataset(_synth.inject_dead_dimension(_synth.clean_dataset(n_episodes=40)))
    report = scan(path, max_episode_memory_mb=1)
    # The profile still sees every episode, so profile-driven detectors are unaffected.
    assert report.dataset.n_episodes == 40
    assert report.cluster("stats.dead_dimension") is not None
