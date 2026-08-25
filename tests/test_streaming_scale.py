"""Streaming-scale properties: quantile accuracy, throughput, and the optimized hot paths.

These are the assertions behind three Tier-3 claims that would otherwise be assertions:

* **Quantiles do not need a sketch.** The reservoir's q01/q99 rank error is *measured* here,
  which is what closes the t-digest deferral. t-digest has no worst-case bound, so replacing a
  measured-accurate estimator with it would be a downgrade dressed as an upgrade.
* **The streaming path is fast enough to reach OXE scale.** The per-row Python loop it replaced
  ran at ~1.4 M rows/s.
* **The optimized DTW and KS primitives are exactly equivalent** to the references they
  replaced. A 4× scan speedup that changes any finding is not a speedup, it is a regression.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np
import pytest
from scipy.stats import ks_2samp

from bohrin._arrays import FloatArray
from bohrin.analysis.neighbors import ks_statistic
from bohrin.analysis.shapes import dtw_distance, pairwise_distances
from bohrin.profile.dataset_profile import DEFAULT_RESERVOIR_ROWS
from bohrin.profile.online import Reservoir

# --------------------------------------------------------- quantiles: the t-digest question

#: Tolerance multiple on the *theoretical* sampling error of a quantile estimated from ``n``
#: uniform draws, ``√(p(1−p)/n)``. Deriving the bar rather than picking a constant is the point:
#: it encodes why the tails are far more accurate than the median (``p(1−p)`` is 100× smaller at
#: p=0.01 than at p=0.5), and it scales automatically with the reservoir size.
#:
#: Three sigma, so an honest run essentially never trips it while a broken estimator — or a
#: reservoir that has quietly stopped being uniform — fails immediately.
_SIGMA_ALLOWANCE = 3.0


def _rank_tolerance(p: float, n: int) -> float:
    """3σ sampling error for the rank of the ``p``-quantile estimated from ``n`` draws."""
    return _SIGMA_ALLOWANCE * float(np.sqrt(p * (1.0 - p) / n))


_StreamFn = Callable[[np.random.Generator, int], FloatArray]

_STREAMS: dict[str, _StreamFn] = {
    "normal": lambda rng, m: rng.normal(size=m),
    "lognormal": lambda rng, m: rng.lognormal(0.0, 1.5, size=m),
    "bimodal": lambda rng, m: np.concatenate([rng.normal(-5, 0.3, m // 2), rng.normal(5, 0.3, m - m // 2)]),
    "exponential-tail": lambda rng, m: rng.exponential(2.0, size=m),
}


@pytest.mark.parametrize("stream", sorted(_STREAMS))
def test_reservoir_quantiles_are_accurate_enough_to_need_no_sketch(stream: str) -> None:
    """Measured rank error for q01/q50/q99 over a 2 M-value stream.

    "Rank error" is the honest metric: it asks what true quantile the estimate actually sits
    at. A value error would be unfairly flattering on a heavy tail and unfairly harsh on a
    tight one.
    """
    rng = np.random.default_rng(0)
    data = _STREAMS[stream](rng, 2_000_000)
    for trial in range(3):
        reservoir = Reservoir(DEFAULT_RESERVOIR_ROWS, np.random.default_rng(trial))
        reservoir.update(data.reshape(-1, 1))
        estimates = np.quantile(reservoir.values(), [0.01, 0.5, 0.99], axis=0).ravel()
        for target, estimate in zip((0.01, 0.5, 0.99), estimates, strict=True):
            actual_rank = float((data <= estimate).mean())
            tolerance = _rank_tolerance(target, DEFAULT_RESERVOIR_ROWS)
            assert abs(actual_rank - target) <= tolerance, (
                f"{stream}: q{target:g} estimate sits at rank {actual_rank:.4f} "
                f"(error {abs(actual_rank - target):.4f} > 3σ = {tolerance:.4f})"
            )


def test_quantile_accuracy_is_reproducible_under_a_seed() -> None:
    """The reservoir's other advantage over a sketch: the same seed gives the same sample."""
    data = np.random.default_rng(1).normal(size=(200_000, 3))

    def run() -> FloatArray:
        reservoir = Reservoir(5_000, np.random.default_rng(99))
        reservoir.update(data)
        return np.asarray(np.quantile(reservoir.values(), [0.01, 0.99], axis=0), dtype=np.float64)

    assert np.array_equal(run(), run())


# ------------------------------------------------------------------- streaming throughput


def test_reservoir_sampling_is_uniform_over_the_whole_stream() -> None:
    """Vectorizing the draws must not disturb Algorithm R's uniformity."""
    total, capacity = 200_000, 2_000
    late = []
    for seed in range(20):
        reservoir = Reservoir(capacity, np.random.default_rng(seed))
        reservoir.update(np.arange(total, dtype=np.float64).reshape(-1, 1))
        values = reservoir.values().ravel()
        assert values.shape[0] == capacity
        late.append(float((values >= total / 2).mean()))
    assert 0.45 <= float(np.mean(late)) <= 0.55


def test_reservoir_handles_batched_and_single_row_updates_identically_in_distribution() -> None:
    """Batch boundaries must not affect the sample's distribution, only its RNG draws."""
    data = np.arange(50_000, dtype=np.float64).reshape(-1, 1)
    one_shot = Reservoir(1_000, np.random.default_rng(3))
    one_shot.update(data)
    chunked = Reservoir(1_000, np.random.default_rng(3))
    for start in range(0, data.shape[0], 997):  # deliberately not a divisor
        chunked.update(data[start : start + 997])
    assert one_shot.seen == chunked.seen == 50_000
    # Not identical row-for-row (the draws differ), but both uniform over the stream.
    for reservoir in (one_shot, chunked):
        assert 0.4 <= float((reservoir.values().ravel() >= 25_000).mean()) <= 0.6


def test_streaming_throughput_is_adequate_for_oxe_scale() -> None:
    """A soft floor: the per-row loop this replaced managed ~1.4 M rows/s.

    Deliberately generous (10× below what was measured) so the test asserts "the vectorized
    path is still in use" rather than pinning a number to whatever machine CI runs on.
    """
    rows = 1_000_000
    data = np.random.default_rng(0).normal(size=(rows, 7))
    reservoir = Reservoir(DEFAULT_RESERVOIR_ROWS, np.random.default_rng(1))
    start = time.perf_counter()
    reservoir.update(data)
    elapsed = time.perf_counter() - start
    rate = rows / elapsed
    assert rate > 5e6, f"reservoir ingest fell to {rate / 1e6:.1f}M rows/s — the per-row loop is back"


def test_reservoir_rejects_a_dimension_change() -> None:
    reservoir = Reservoir(10, np.random.default_rng(0))
    reservoir.update(np.zeros((5, 3)))
    with pytest.raises(ValueError, match="dimension mismatch"):
        reservoir.update(np.zeros((5, 4)))


def test_reservoir_ignores_empty_batches() -> None:
    reservoir = Reservoir(10, np.random.default_rng(0))
    reservoir.update(np.zeros((0, 3)))
    assert reservoir.seen == 0
    assert reservoir.values().shape == (0, 3)


# ------------------------------------------------- the optimized primitives are equivalent


def _reference_dtw(a: FloatArray, b: FloatArray, band: int = 10) -> float:
    """The original implementation: `np.linalg.norm` inside the DP loop."""
    n, m = a.shape[0], b.shape[0]
    if n == 0 or m == 0:
        return float("inf")
    width = max(band, abs(n - m) + 1)
    cost = np.full((n + 1, m + 1), np.inf)
    cost[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(max(1, i - width), min(m, i + width) + 1):
            d = float(np.linalg.norm(a[i - 1] - b[j - 1]))
            cost[i, j] = d + min(cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])
    result = cost[n, m]
    return float(result / (n + m)) if np.isfinite(result) else float("inf")


def test_optimized_dtw_matches_the_reference_implementation() -> None:
    """A 7× speedup that changes a distance would silently move every CONSISTENCY finding."""
    rng = np.random.default_rng(0)
    worst = 0.0
    for _ in range(200):
        n, m, d = (int(rng.integers(1, 40)), int(rng.integers(1, 40)), int(rng.integers(1, 8)))
        a, b = rng.normal(size=(n, d)), rng.normal(size=(m, d))
        fast, slow = dtw_distance(a, b), _reference_dtw(a, b)
        if np.isinf(slow):
            assert np.isinf(fast)
            continue
        worst = max(worst, abs(fast - slow) / max(abs(slow), 1e-12))
    assert worst < 1e-9, f"optimized DTW diverged from the reference by {worst:.2e}"


def test_dtw_is_symmetric() -> None:
    """The property the detector's upper-triangle optimization relies on."""
    rng = np.random.default_rng(1)
    for _ in range(50):
        a, b = rng.normal(size=(24, 6)), rng.normal(size=(24, 6))
        assert dtw_distance(a, b) == pytest.approx(dtw_distance(b, a), rel=1e-12)


def test_pairwise_distances_matches_the_naive_form() -> None:
    rng = np.random.default_rng(2)
    a, b = rng.normal(size=(17, 5)), rng.normal(size=(23, 5))
    naive = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)
    assert np.allclose(pairwise_distances(a, b), naive, atol=1e-10)


def test_ks_statistic_matches_scipy_including_heavy_ties() -> None:
    """Ties are the realistic case: the inputs are integer index distances."""
    rng = np.random.default_rng(3)
    worst = 0.0
    for _ in range(300):
        n, m = int(rng.integers(2, 200)), int(rng.integers(2, 200))
        a = rng.integers(0, 40, size=n).astype(float)
        b = rng.integers(0, 40, size=m).astype(float)
        worst = max(worst, abs(ks_statistic(a, np.sort(b)) - float(ks_2samp(a, b).statistic)))
    assert worst < 1e-12, f"KS statistic diverged from scipy by {worst:.2e}"


def test_ks_statistic_handles_empty_input() -> None:
    assert ks_statistic(np.empty(0), np.sort(np.array([1.0, 2.0]))) == 0.0
