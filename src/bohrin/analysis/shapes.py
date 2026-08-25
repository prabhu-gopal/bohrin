"""Trajectory shape primitives: resampling, DTW, intrinsic dimensionality, modality.

Shared math used by the COVERAGE / CONSISTENCY / MULTIMODALITY families. Everything here
is format-agnostic — it operates on plain ``(T, D)`` arrays from the Canonical IR.
"""

from __future__ import annotations

import numpy as np
from sklearn.mixture import GaussianMixture

from bohrin._arrays import FloatArray
from bohrin.analysis.robust import finite_row_mask

_EPS = 1e-12


def resample(traj: FloatArray, n: int) -> FloatArray:
    """Resample a ``(T, D)`` trajectory to exactly ``n`` points on normalized time.

    Puts trajectories of different durations on a common footing so their *shapes* can be
    compared directly (the basis of mode-collapse detection).
    """
    t = traj.shape[0]
    if t == 0:
        return np.zeros((n, traj.shape[1] if traj.ndim == 2 else 1), dtype=np.float64)
    if t == 1:
        return np.repeat(traj, n, axis=0).astype(np.float64)
    src = np.linspace(0.0, 1.0, t)
    dst = np.linspace(0.0, 1.0, n)
    out = np.empty((n, traj.shape[1]), dtype=np.float64)
    for d in range(traj.shape[1]):
        out[:, d] = np.interp(dst, src, traj[:, d])
    return out


def path_length(traj: FloatArray) -> float:
    """Total travelled distance along a trajectory."""
    if traj.shape[0] < 2:
        return 0.0
    return float(np.sum(np.linalg.norm(np.diff(traj, axis=0), axis=1)))


def top_variance_ratio(points: FloatArray) -> float:
    """Fraction of variance captured by the first principal component.

    Near 1.0 means the sampled states lie on a one-dimensional "thin tube" — the geometric
    signature of a dataset that only ever demonstrates one path through the workspace.
    """
    if points.shape[0] < 3 or points.shape[1] < 2:
        return 0.0
    centered = points - points.mean(axis=0)
    # Singular values² are proportional to the explained variance per component.
    sv = np.linalg.svd(centered, compute_uv=False)
    total = float(np.sum(sv**2))
    if total <= _EPS:
        return 1.0
    return float(sv[0] ** 2 / total)


def pairwise_distances(a: FloatArray, b: FloatArray) -> FloatArray:
    """Euclidean distance between every point of ``a`` and every point of ``b`` — ``(n, m)``.

    Computed via the expanded inner-product form rather than broadcasting an ``(n, m, D)``
    difference, so memory stays ``O(n·m)`` instead of ``O(n·m·D)``.
    """
    aa = np.sum(a * a, axis=1)[:, None]
    bb = np.sum(b * b, axis=1)[None, :]
    # On some BLAS backends (observed with Apple Accelerate under Python 3.10) `a @ b.T` can
    # raise a spurious RuntimeWarning for finite, well-formed inputs — an internal FPE flag
    # from the GEMM microkernel, not a real division. The clamp to 0.0 immediately after
    # already guards the one thing that could actually go wrong (a tiny negative from
    # floating-point cancellation), so a warning here carries no information.
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        sq = np.maximum(aa + bb - 2.0 * (a @ b.T), 0.0)
    out: FloatArray = np.sqrt(sq)
    return out


def dtw_distance(a: FloatArray, b: FloatArray, *, band: int = 10) -> float:
    """Sakoe-Chiba banded dynamic time warping distance between two ``(T, D)`` series.

    The band bounds the warp so the cost is O(T·band) rather than O(T²), which keeps the
    pairwise matrix affordable over a reservoir of episodes.

    **Why the implementation looks like this.** Measured on a 120-episode scan, this function
    was **71 % of total runtime** — the single hot spot in the whole battery. The cause was not
    the algorithm but the constant factor: the original computed ``np.linalg.norm`` *inside* the
    DP loop, paying NumPy's per-call dispatch overhead once per cell (~780 k times for one
    detector). Two changes fix that without touching the result:

    * the point-to-point distances are computed **once, vectorized**, before the recurrence;
    * the recurrence itself runs on Python floats in a flat list. The DP is inherently
      sequential (``cost[i][j]`` depends on ``cost[i][j-1]``), so there is nothing to vectorize
      — and for scalar work a Python float beats a 0-d NumPy array comfortably.
    """
    n, m = a.shape[0], b.shape[0]
    if n == 0 or m == 0:
        return float("inf")
    width = max(band, abs(n - m) + 1)
    dist = pairwise_distances(a, b)

    inf = float("inf")
    # Two rolling rows of the cost matrix; only the previous row is ever read.
    previous = [inf] * (m + 1)
    previous[0] = 0.0
    for i in range(1, n + 1):
        current = [inf] * (m + 1)
        row = dist[i - 1]
        lo = max(1, i - width)
        hi = min(m, i + width)
        left = current[lo - 1]
        for j in range(lo, hi + 1):
            best = previous[j]
            diagonal = previous[j - 1]
            if diagonal < best:
                best = diagonal
            if left < best:
                best = left
            left = row[j - 1] + best
            current[j] = left
        previous = current
    result = previous[m]
    return result / (n + m) if result != inf else inf


def is_multimodal(
    samples: FloatArray,
    *,
    min_samples: int = 24,
    bic_margin: float = 10.0,
    min_separation: float = 2.0,
    min_weight: float = 0.15,
    min_gap: float = 0.0,
) -> bool:
    """Whether ``samples`` are genuinely better explained by two Gaussian modes than one.

    Three independent hurdles, because a BIC comparison alone is not safe here:

    1. **BIC margin** — two components must beat one decisively.
    2. **Mode separation** — the component means must be at least ``min_separation`` pooled
       standard deviations apart. Without this, near-identical data is "bimodal": its
       variance is ~0, so the fitted likelihood explodes and BIC prefers two components that
       are really just two halves of the same noise cloud.
    3. **Balanced weights** — both modes must carry real mass, so a single stray point
       cannot masquerade as a second mode.

    ``min_gap`` adds an absolute floor on the distance between the modes. Callers use it to
    reject *temporal aliasing*: when the state barely moves between consecutive steps, a
    neighbourhood mixes adjacent timesteps whose actions naturally differ, which is not two
    demonstrations disagreeing.
    """
    # GaussianMixture raises on NaN/inf. A neighbourhood is an unordered sample set here, so
    # dropping corrupt rows is safe; `integrity.nan_inf` reports them.
    mask = finite_row_mask(samples)
    if mask.size and not bool(mask.all()):
        samples = samples[mask]
    n = samples.shape[0]
    if n < min_samples:
        return False
    if float(np.max(np.std(samples, axis=0))) < _EPS:
        return False
    try:
        # Diagonal covariance keeps the parameter count low, which matters at the small
        # neighbourhood sizes these are fitted on — a full covariance would be unstable and
        # could "discover" modes in ordinary noise.
        #
        # `samples` was already validated finite and non-degenerate above, so a RuntimeWarning
        # from inside sklearn's internal matmuls here (observed on some BLAS backends, e.g.
        # under Python 3.10) reflects an internal FPE flag, not a real problem with our input.
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            one = GaussianMixture(n_components=1, covariance_type="diag", random_state=0).fit(samples)
            two = GaussianMixture(n_components=2, covariance_type="diag", random_state=0).fit(samples)
    except ValueError:
        return False
    if one.bic(samples) - two.bic(samples) <= bic_margin:
        return False
    if float(np.min(two.weights_)) < min_weight:
        return False
    gap = float(np.linalg.norm(two.means_[0] - two.means_[1]))
    if gap < min_gap:
        return False
    pooled_sd = float(np.mean(np.sqrt(two.covariances_)))
    if pooled_sd < _EPS:
        return False
    return gap / pooled_sd > min_separation
