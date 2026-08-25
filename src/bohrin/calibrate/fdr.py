"""False-discovery-rate control over conformal p-values (docs/07 §4.1).

A scan tests *many* units at once — every episode, every step, every dimension — against
the same reference band. That is a multiple-testing problem, and it is precisely why the
naive gate ``p ≤ fpr`` was never usable as a gate: applied to ``m`` in-distribution units it
flags ``≈ fpr · m`` of them **by construction**, so a 300-episode clean dataset would show
~3 false findings at ``--fpr 0.01``. The battery therefore retreated to hand-picked robust-z
constants and ``--fpr`` only ever coloured the *confidence* (docs/06, deviation 3).

The fix is the Benjamini–Hochberg step-up procedure. Two properties make it the right
instrument here:

1. **It controls the false-discovery rate, not the per-unit error rate.** BH at level ``q``
   bounds the *expected proportion of false findings among those reported*, which is the
   quantity a user actually cares about ("how much of this report is noise?").
2. **Under the global null it reports nothing.** If every unit is in-distribution, the
   probability that BH makes even one rejection is at most ``q``. That is the zero-false-HIGH
   bar as a theorem rather than a hand-tuned threshold — the thing the magic constants were
   standing in for.

Conformal p-values computed against a *shared* calibration set are not independent — they
are mutually dependent through that set — so the applicability of BH is not automatic.
Bates, Candès, Lei, Romano & Sesia (*Testing for Outliers with Conformal p-values*, Annals
of Statistics 51(1):149–178, 2023; arXiv 2104.08279) settle it: conformal p-values built
this way are PRDS, and BH retains FDR control under exactly this dependence. That result is
what licenses the gate in :mod:`bohrin.calibrate.gate`.
"""

from __future__ import annotations

import numpy as np

from bohrin._arrays import BoolArray, FloatArray


def bh_cutoff(pvalues: FloatArray, q: float) -> float:
    """The Benjamini–Hochberg rejection cutoff for ``pvalues`` at FDR level ``q``.

    Returns the largest p-value that BH rejects, or ``0.0`` when it rejects nothing. Because
    conformal p-values are discrete and ties are common (many units can share a rank against
    a finite reference band), the cutoff is returned as a *value* rather than a count: the
    caller then rejects ``p ≤ cutoff``, which treats tied units identically instead of
    letting an arbitrary sort order decide which of two identical scores is reported.
    """
    p = np.asarray(pvalues, dtype=np.float64).ravel()
    m = p.size
    if m == 0 or not 0.0 < q < 1.0:
        return 0.0
    ordered = np.sort(p, kind="stable")
    # BH: reject the k smallest, where k = max{ i : p₍ᵢ₎ ≤ q·i/m }  (1-based i).
    ladder = q * np.arange(1, m + 1, dtype=np.float64) / m
    below = ordered <= ladder
    if not below.any():
        return 0.0
    return float(ordered[int(np.flatnonzero(below)[-1])])


def benjamini_hochberg(pvalues: FloatArray, q: float) -> BoolArray:
    """Rejection mask for ``pvalues`` at FDR level ``q`` (the BH step-up procedure).

    All-``False`` when nothing survives — the common and correct outcome on clean data.
    """
    p = np.asarray(pvalues, dtype=np.float64).ravel()
    cutoff = bh_cutoff(p, q)
    if cutoff <= 0.0:
        return np.zeros(p.shape, dtype=np.bool_)
    rejected: BoolArray = p <= cutoff
    return rejected
