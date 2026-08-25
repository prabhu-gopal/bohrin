"""Inductive Conformal Anomaly Detection — the calibration layer (docs/07 §4, docs/02 §3.5).

Threshold-based detectors do not compare a metric to a magic constant. They emit a
**non-conformity score** per unit (episode / step / dimension), and this module turns those
scores into **conformal p-values** calibrated against the dataset's own clean bulk. The
user sets one knob, ``--fpr``: under exchangeability, the probability that a genuinely
in-distribution unit is flagged is at most ``fpr`` — a finite-sample, distribution-free
bound. A finding's ``confidence`` is then ``1 − p``, comparable across every detector.

Reference: conformal prediction gives finite-sample coverage under minimal exchangeability
assumptions (CODiT, arXiv 2207.11769; onboard conformal OOD, arXiv 2405.02634).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bohrin._arrays import BoolArray, FloatArray
from bohrin._compat import StrEnum
from bohrin.calibrate.fdr import benjamini_hochberg


class Selection(StrEnum):
    """How ``is_anomaly`` is derived from the conformal p-values.

    ``PER_UNIT`` is the textbook ICAD rule ``p ≤ fpr``: it bounds the error rate for *one*
    unit, and consequently flags ~``fpr`` of a large in-distribution batch. Use it when the
    question really is about a single unit.

    ``FDR_BH`` applies Benjamini–Hochberg across the batch. It bounds the expected share of
    false findings among those reported and, under the global null, reports nothing at all
    with probability ≥ ``1 − fpr``. This is the correct rule for a *gate*, which is always a
    simultaneous decision over many units (see :mod:`bohrin.calibrate.fdr`).
    """

    PER_UNIT = "per_unit"
    FDR_BH = "fdr_bh"


@dataclass(frozen=True, slots=True)
class CalibratedScores:
    """The result of calibrating a batch of non-conformity scores."""

    scores: FloatArray
    pvalues: FloatArray  # conformal p-value per unit (smaller = more anomalous)
    confidence: FloatArray  # 1 − p, the finding's confidence
    is_anomaly: BoolArray  # selected by the chosen ``Selection`` rule
    fpr: float
    selection: Selection = Selection.PER_UNIT

    @property
    def anomaly_indices(self) -> list[int]:
        """Indices flagged as anomalies, most-anomalous first."""
        idx = np.nonzero(self.is_anomaly)[0]
        order = np.argsort(self.pvalues[idx], kind="stable")
        return [int(i) for i in idx[order]]


class ConformalCalibrator:
    """Calibrates non-conformity scores to conformal p-values at a target FPR."""

    def __init__(self, fpr: float) -> None:
        if not 0.0 < fpr < 1.0:
            raise ValueError(f"fpr must be in (0, 1); got {fpr}")
        self.fpr = fpr

    def calibrate(
        self,
        scores: FloatArray,
        *,
        calibration: FloatArray | None = None,
        selection: Selection = Selection.PER_UNIT,
    ) -> CalibratedScores:
        """Return p-values and anomaly flags for ``scores``.

        By default the scores calibrate against themselves (the clean majority sets the
        reference distribution for the dirty minority). Pass ``calibration`` to use a
        supplied known-good reference set instead.

        Higher score ⇒ more anomalous. The p-value of a unit with score ``s`` is
        ``(1 + #{cal ≥ s}) / (n + 1)`` — the standard ICAD estimator.

        ``selection`` chooses how those p-values become flags; see :class:`Selection`. The
        default stays ``PER_UNIT`` so existing callers that only want ``confidence`` are
        unaffected, but a *gate* should pass ``FDR_BH``.
        """
        s = np.asarray(scores, dtype=np.float64).ravel()
        if s.size == 0:
            empty = np.empty(0, dtype=np.float64)
            return CalibratedScores(empty, empty, empty, np.empty(0, dtype=np.bool_), self.fpr, selection)

        cal = s if calibration is None else np.asarray(calibration, dtype=np.float64).ravel()
        n = cal.shape[0]
        sorted_cal = np.sort(cal)
        # #{cal ≥ s} = n − (index of first cal element ≥ s).
        counts_ge = n - np.searchsorted(sorted_cal, s, side="left")
        pvalues: FloatArray = ((1.0 + counts_ge) / (n + 1.0)).astype(np.float64)
        is_anomaly: BoolArray = (
            benjamini_hochberg(pvalues, self.fpr) if selection is Selection.FDR_BH else pvalues <= self.fpr
        )
        confidence: FloatArray = (1.0 - pvalues).astype(np.float64)
        return CalibratedScores(
            scores=s,
            pvalues=pvalues,
            confidence=confidence,
            is_anomaly=is_anomaly,
            fpr=self.fpr,
            selection=selection,
        )
