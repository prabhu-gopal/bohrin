"""Kernel two-sample testing — MMD (docs/07 §6).

Maximum Mean Discrepancy with an RBF kernel is a proper distribution-free two-sample test
that works directly on embeddings, replacing PSI/KS heuristics for drift and skew. The
bandwidth uses the standard **median heuristic**; significance comes from a **permutation
test**, which gives an exact finite-sample p-value with no distributional assumptions.

Reference: Gretton et al., *A Kernel Two-Sample Test*, JMLR 13 (2012).
The same primitive is the designated statistic for L2's cross-version skew.
"""

from __future__ import annotations

import numpy as np

from bohrin._arrays import FloatArray
from bohrin.analysis.robust import finite_row_mask

_EPS = 1e-12


def _finite_rows(sample: FloatArray) -> FloatArray:
    """Rows of ``sample`` with no NaN/±inf (see :func:`mmd_permutation_test`)."""
    mask = finite_row_mask(sample)
    if mask.size == 0 or bool(mask.all()):
        return sample
    return sample[mask]


def median_heuristic_gamma(pooled: FloatArray) -> float:
    """RBF ``gamma = 1 / (2·median_pairwise_distance²)`` — the standard bandwidth choice."""
    n = pooled.shape[0]
    if n < 2:
        return 1.0
    # Subsample for the heuristic so this stays cheap on large pools.
    idx = np.arange(n) if n <= 512 else np.linspace(0, n - 1, 512).astype(np.int64)
    sub = pooled[idx]
    sq = _sq_dists(sub, sub)
    upper = sq[np.triu_indices(sub.shape[0], k=1)]
    med = float(np.median(upper)) if upper.size else 1.0
    if med <= _EPS:
        return 1.0
    return 1.0 / med  # med is already a squared distance → gamma = 1/(2σ²) with σ²=med/2


def _sq_dists(a: FloatArray, b: FloatArray) -> FloatArray:
    sq: FloatArray = np.sum(a**2, axis=1)[:, None] + np.sum(b**2, axis=1)[None, :] - 2.0 * (a @ b.T)
    return np.maximum(sq, 0.0)


def _rbf(a: FloatArray, b: FloatArray, gamma: float) -> FloatArray:
    out: FloatArray = np.exp(-gamma * _sq_dists(a, b))
    return out


def mmd2_unbiased(x: FloatArray, y: FloatArray, gamma: float) -> float:
    """Unbiased estimator of the squared MMD between two samples."""
    n, m = x.shape[0], y.shape[0]
    if n < 2 or m < 2:
        return 0.0
    kxx = _rbf(x, x, gamma)
    kyy = _rbf(y, y, gamma)
    kxy = _rbf(x, y, gamma)
    # Exclude the diagonal for the unbiased within-sample terms.
    sum_xx = float(kxx.sum() - np.trace(kxx)) / (n * (n - 1))
    sum_yy = float(kyy.sum() - np.trace(kyy)) / (m * (m - 1))
    sum_xy = float(kxy.mean())
    return float(sum_xx + sum_yy - 2.0 * sum_xy)


def mmd_permutation_test(
    x: FloatArray,
    y: FloatArray,
    *,
    rng: np.random.Generator,
    n_permutations: int = 200,
) -> tuple[float, float]:
    """Return ``(mmd², p_value)`` for H0: x and y come from the same distribution.

    The p-value is the fraction of label-shuffled permutations whose MMD² is at least the
    observed one (with the standard +1 correction), so it is exact and finite-sample valid.

    Non-finite rows are excluded from both samples first. A NaN makes every kernel entry in its
    row NaN, and the permutation comparison ``mmd² >= observed`` is then always ``False`` — so
    the count stays at zero, the p-value collapses to its floor, and the test reports a
    *maximally significant* drift on the strength of one corrupt cell. Both samples are
    unordered here, so filtering is safe; the corruption is reported by ``integrity.nan_inf``.
    """
    x = _finite_rows(x)
    y = _finite_rows(y)
    if x.shape[0] < 2 or y.shape[0] < 2:
        return 0.0, 1.0
    pooled = np.vstack([x, y])
    gamma = median_heuristic_gamma(pooled)
    observed = mmd2_unbiased(x, y, gamma)
    n = x.shape[0]
    count = 0
    for _ in range(n_permutations):
        perm = rng.permutation(pooled.shape[0])
        shuffled = pooled[perm]
        if mmd2_unbiased(shuffled[:n], shuffled[n:], gamma) >= observed:
            count += 1
    p_value = (count + 1.0) / (n_permutations + 1.0)
    return observed, p_value
