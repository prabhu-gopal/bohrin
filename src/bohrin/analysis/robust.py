"""Robust (outlier-resistant) location/scale statistics.

Lives in ``analysis`` rather than in the detector helpers because both layers need it: the
detector battery uses it directly, and the calibration gate uses it as the *fallback* rule
when no reference band is available (:mod:`bohrin.calibrate.gate`). One implementation keeps
the two paths from drifting apart.
"""

from __future__ import annotations

import numpy as np

from bohrin._arrays import BoolArray, FloatArray

_EPS = 1e-12


def finite_row_mask(*arrays: FloatArray) -> BoolArray:
    """Mask of rows that are finite in **every** input array.

    Arrays must share a leading dimension; 1-D inputs are treated as one column.
    """
    mask: BoolArray | None = None
    for array in arrays:
        a = np.asarray(array, dtype=np.float64)
        rows = np.isfinite(a) if a.ndim == 1 else np.isfinite(a).all(axis=1)
        mask = rows if mask is None else (mask & rows)
    if mask is None:
        return np.empty(0, dtype=np.bool_)
    return mask


def keep_finite_rows(*arrays: FloatArray) -> tuple[FloatArray, ...]:
    """Drop rows that are non-finite in any input, preserving alignment across arrays.

    **Why every model fit needs this.** NaN and ±inf are among the most common real-world data
    defects — they are what ``integrity.nan_inf`` exists to report — but the solvers underneath
    the battery do not tolerate them: ``numpy.linalg.lstsq`` raises ``LinAlgError: SVD did not
    converge``, and scikit-learn's ``Ridge``/``NearestNeighbors`` raise ``ValueError``. Four
    detectors (``causal.copycat_shortcut``, ``coverage.redundancy`` and both DYNAMICS residual
    checks) crashed the entire scan on a single NaN, which is a strictly worse failure than any
    false positive: the user loses the report that would have told them about the NaN.

    Dropping the offending rows is the right response rather than refusing to run. The corrupt
    rows are already reported by INTEGRITY, so re-reporting them here would be noise, and the
    remaining ninety-nine percent of the data still deserves analysis.
    """
    mask = finite_row_mask(*arrays)
    return tuple(np.asarray(a, dtype=np.float64)[mask] for a in arrays)


#: Consistency constant making the MAD an unbiased estimator of σ for Gaussian data.
#: ``0.6745 ≈ Φ⁻¹(0.75)``, so ``0.6745·(x−med)/MAD`` is on the same scale as a z-score.
MAD_TO_SIGMA = 0.6745


def mad_scores(values: FloatArray) -> FloatArray:
    """Robust z-scores via the median-absolute-deviation (MAD).

    ``0.6745 · (x − median) / MAD`` — a heavy-tail-resistant standardization. Returns zeros
    when the MAD is degenerate (all equal), so a constant signal never yields outliers.
    """
    x = np.asarray(values, dtype=np.float64).ravel()
    if x.size == 0:
        return x
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    if mad < _EPS:
        return np.zeros_like(x)
    return MAD_TO_SIGMA * (x - med) / mad
