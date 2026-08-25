"""Nearest-neighbour primitives: kNN, the non-IID test, and effective diversity (docs/07 §2, §5).

``non_iid_pvalue`` implements cleanlab's published kNN test: compare the distribution of
*index distances* between feature-space neighbours (foreground) against random pairs
(background) with a KS statistic and a permutation p-value. A low p-value means points that
are adjacent in collection order are also adjacent in feature space — i.e. near-duplicate,
session-clustered sampling, which is exactly how redundant robot demonstrations look.

``effective_diversity`` turns that into the headline number: how many *genuinely distinct*
demonstrations a dataset actually carries, which the Data Scaling Laws result (ICLR 2025
Oral, arXiv 2410.18647) shows matters far more than raw count.

Reference: *Detecting Dataset Drift and Non-IID Sampling via k-Nearest Neighbors*
(arXiv 2305.15696).
"""

from __future__ import annotations

import numpy as np
from sklearn.neighbors import NearestNeighbors

from bohrin._arrays import FloatArray, IntArray
from bohrin.analysis.robust import finite_row_mask

_EPS = 1e-12


#: Above this many points, exact kNN gets expensive and the ANN backend is preferred.
ANN_THRESHOLD = 20_000


def knn(points: FloatArray, k: int) -> tuple[FloatArray, IntArray]:
    """Return ``(distances, indices)`` of the ``k`` nearest neighbours, excluding self.

    Uses exact search by default. On large inputs it will use **FAISS** if ``bohrin[ann]`` is
    installed, turning an O(n²)-ish exact search into a million-scale-feasible index
    (docs/09 §1.2); without FAISS it falls back to exact search, which stays correct — just
    slower. The result shape and semantics are identical either way.
    """
    n = points.shape[0]
    if n < 2:
        return np.zeros((n, 1), dtype=np.float64), np.zeros((n, 1), dtype=np.int64)
    k_eff = max(1, min(k, n - 1))
    if n > ANN_THRESHOLD:
        approx = _faiss_knn(points, k_eff)
        if approx is not None:
            return approx
    nn = NearestNeighbors(n_neighbors=k_eff + 1).fit(points)
    dist, idx = nn.kneighbors(points)
    return dist[:, 1:].astype(np.float64), idx[:, 1:].astype(np.int64)


def finite_points(points: FloatArray) -> FloatArray:
    """Drop rows containing NaN/inf — the neighbour backends raise ``ValueError`` on them.

    Applied by the *set-semantics* consumers below (:func:`non_iid_pvalue`,
    :func:`effective_diversity`), which treat their input as an unordered point cloud. It is
    deliberately **not** applied inside :func:`knn`: that function's contract is that row ``i``
    of its result describes row ``i`` of its input, and quietly renumbering rows there would
    make callers that map an index back to an episode report the wrong episode. Those callers
    filter their own aligned arrays jointly instead (see ``keep_finite_rows``).

    A single NaN anywhere in the reservoir used to abort the entire scan here.
    """
    mask = finite_row_mask(points)
    if mask.size == 0 or bool(mask.all()):
        return points
    return points[mask]


def _faiss_knn(points: FloatArray, k: int) -> tuple[FloatArray, IntArray] | None:
    """FAISS-backed kNN, or ``None`` when the optional extra is not installed."""
    try:
        import faiss
    except ImportError:
        return None
    data = np.ascontiguousarray(points, dtype=np.float32)
    index = faiss.IndexHNSWFlat(data.shape[1], 32)
    index.add(data)
    dist, idx = index.search(data, k + 1)
    return np.sqrt(np.maximum(dist[:, 1:], 0.0)).astype(np.float64), idx[:, 1:].astype(np.int64)


def ks_statistic(sample: FloatArray, reference_sorted: FloatArray) -> float:
    """Two-sample Kolmogorov–Smirnov statistic against an already-sorted reference.

    Equivalent to ``scipy.stats.ks_2samp(...).statistic`` (asserted in the tests) but without
    re-sorting the reference on every call. The permutation test below evaluates this 200 times
    against the *same* background, so hoisting that sort out of the loop is most of the cost:
    ``coverage.redundancy`` was the battery's slowest detector once DTW was fixed.
    """
    s = np.sort(np.asarray(sample, dtype=np.float64))
    n, m = s.shape[0], reference_sorted.shape[0]
    if n == 0 or m == 0:
        return 0.0
    # Evaluate both empirical CDFs on the pooled support and take the largest gap. `side` is
    # chosen so ties are counted at the top of their run, matching scipy's convention.
    pooled = np.concatenate([s, reference_sorted])
    cdf_sample = np.searchsorted(s, pooled, side="right") / n
    cdf_reference = np.searchsorted(reference_sorted, pooled, side="right") / m
    return float(np.max(np.abs(cdf_sample - cdf_reference)))


def non_iid_pvalue(
    points: FloatArray,
    *,
    rng: np.random.Generator,
    k: int = 5,
    n_permutations: int = 200,
) -> float:
    """Cleanlab-style non-IID p-value. Low ⇒ ordering and feature space are entangled."""
    points = finite_points(points)
    n = points.shape[0]
    if n < 8:
        return 1.0
    _, idx = knn(points, k)
    rows = np.repeat(np.arange(n), idx.shape[1])
    foreground = np.abs(rows - idx.ravel()).astype(np.float64)
    n_bg = min(4 * foreground.size, 20_000)
    a = rng.integers(0, n, size=n_bg)
    b = rng.integers(0, n, size=n_bg)
    keep = a != b
    background = np.abs(a[keep] - b[keep]).astype(np.float64)
    if foreground.size < 2 or background.size < 2:
        return 1.0
    background_sorted = np.sort(background)
    observed = ks_statistic(foreground, background_sorted)

    # Permutation null: shuffle the ordering, keeping the feature-space graph fixed.
    count = 0
    for _ in range(n_permutations):
        perm = rng.permutation(n)
        shuffled = np.abs(perm[rows] - perm[idx.ravel()]).astype(np.float64)
        if ks_statistic(shuffled, background_sorted) >= observed:
            count += 1
    return (count + 1.0) / (n_permutations + 1.0)


def effective_diversity(points: FloatArray, *, quantile: float = 0.25, radius: float | None = None) -> int:
    """Number of distinct items, via a greedy cover at a "same thing" radius.

    Points within ``radius`` of an already-chosen representative are treated as
    near-duplicates; the return value is how many representatives it takes to cover the set —
    the "you have N demos but the diversity of M" number.

    By default the radius is a low quantile of nearest-neighbour distances, which is
    scale-free and works when the question is *relative* redundancy. Pass an explicit
    ``radius`` when you have a meaningful physical scale for "identical" — e.g. sensor noise,
    which is what makes "all these demos are the same scene" decidable rather than relative.
    """
    points = finite_points(points)
    n = int(points.shape[0])
    if n < 3:
        return n
    # Nearest-neighbour distances serve two purposes: the default radius, and the greedy
    # ordering (start from the most isolated points so representatives are well spread).
    dist, _ = knn(points, 1)
    if radius is None:
        radius = float(np.quantile(dist[:, 0], quantile))
    if radius <= _EPS:
        return 1
    chosen: list[int] = []
    covered = np.zeros(n, dtype=bool)
    order = np.argsort(-dist[:, 0])  # start from the most isolated points
    for i in order:
        if covered[i]:
            continue
        chosen.append(int(i))
        d = np.linalg.norm(points - points[i], axis=1)
        covered |= d <= radius
    return len(chosen)
