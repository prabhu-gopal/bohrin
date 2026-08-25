"""The gate: turning non-conformity scores into flagged units (docs/07 §4.2).

Every threshold-based detector in the battery has the same shape — compute one score per
unit (episode / step / dimension), then decide which units are bad enough to report. This
module owns that second half, and it is the seam where ``--fpr`` becomes real.

**Two rules, and the tool always says which one it used.**

``CONFORMAL_FDR`` — a reference band for this ``(detector, embodiment)`` pair exists in the
calibration corpus, so scores become conformal p-values against *known-good* data and
Benjamini–Hochberg selects at FDR level ``--fpr``. This is the path with a real guarantee:
distribution-free, finite-sample, and (because the corpus is keyed by embodiment) conditional
on the robot rather than averaged over a corpus that might be mostly one arm.

``ROBUST_Z`` — no band available, so the gate falls back to the documented robust-z constant
the battery shipped with, self-calibrated against the dataset's own bulk. This is a heuristic
and is labelled as one. It cannot be replaced by "conformal against ourselves": self-
calibration is a statement about a unit's rank *within this dataset*, so on clean data it
flags the top ``fpr`` fraction no matter how healthy the data is (docs/06, deviation 3).

**A finite band has a resolution limit, and it is not optional.** The smallest p-value a
reference band of ``n`` samples can produce is ``1/(n+1)``. For BH to reject even one of ``m``
tested units at level ``q``, that floor must clear the first rung of the ladder, ``q/m`` —
so the band must satisfy ``n ≥ m/q − 1``. Calibrating 300 episodes at ``--fpr 0.01`` therefore
needs ~30 000 reference scores, and a band of 500 cannot flag *anything*, however extreme.
:func:`gate` computes this requirement and, when a band is too small to support a decision,
falls back to the robust-z rule and says exactly how many more reference scores are needed.
Silently keeping the under-powered conformal path would be the worst option available: it
returns "nothing found" for a structural reason, on the gate whose whole job is finding things.

Two further design points that are easy to get wrong:

* **The effect-size floor is not part of the gate.** Detectors that also require an absolute
  magnitude (a path 2.5× longer than direct, a residual as large as the signal) pass it as
  ``eligible``. Statistical unusualness and practical significance are different questions,
  and conformal calibration only answers the first. A unit 20 σ from the median of a dataset
  whose spread is sensor noise is *unusual* and *irrelevant*; keeping the floor is what
  prevents the guarantee from manufacturing findings nobody should act on.
* **Confidence and selection come from the same p-values.** Under ``CONFORMAL_FDR`` both are
  computed against the band, so a finding's confidence means "how extreme against known-good
  data" rather than "how extreme against its own siblings".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bohrin._arrays import BoolArray, FloatArray
from bohrin._compat import StrEnum
from bohrin.analysis.robust import mad_scores
from bohrin.calibrate.conformal import ConformalCalibrator, Selection
from bohrin.calibrate.corpus import CalibrationCorpus


class GateMethod(StrEnum):
    """Which decision rule produced a finding — recorded in its evidence, never hidden."""

    CONFORMAL_FDR = "conformal_fdr"
    ROBUST_Z = "robust_z"


@dataclass(frozen=True, slots=True)
class GateResult:
    """The outcome of gating one detector's scores."""

    method: GateMethod
    #: Flagged unit indices, most-anomalous (highest score) first.
    flagged: tuple[int, ...]
    #: Per-unit confidence (``1 − p``), aligned with the input scores.
    confidence: FloatArray
    #: Per-unit conformal p-values — against the reference band, or self-calibrated.
    pvalues: FloatArray
    #: Per-unit robust z-scores (always computed; reported as evidence either way).
    robust_z: FloatArray
    scores: FloatArray
    #: The effective cut: a BH p-value cutoff, or the robust-z threshold.
    cut: float
    #: Size of the reference band used; ``0`` when self-calibrated.
    reference_n: int
    #: Set when a band existed but was too small to support a decision over this many units:
    #: ``(band size, samples required)``. The gate then used the robust-z fallback.
    underpowered: tuple[int, int] | None = None

    @property
    def fired(self) -> bool:
        """Whether anything was flagged."""
        return bool(self.flagged)

    @property
    def worst(self) -> int:
        """Index of the most-anomalous flagged unit (``0`` when nothing fired)."""
        return self.flagged[0] if self.flagged else 0

    @property
    def worst_confidence(self) -> float:
        """Confidence of the most-anomalous flagged unit."""
        if not self.flagged or self.confidence.size == 0:
            return 0.0
        return float(self.confidence[self.worst])

    def note(self) -> str:
        """One clause for ``Evidence.notes`` stating how this finding was gated.

        A report that does not distinguish a calibrated gate from a heuristic one invites the
        reader to assume the stronger of the two. Saying it plainly costs one line.
        """
        if self.method is GateMethod.CONFORMAL_FDR:
            return (
                f"gate: conformal FDR (Benjamini–Hochberg) against a {self.reference_n}-sample "
                f"calibration band; p ≤ {self.cut:.4g}"
            )
        if self.underpowered is not None:
            have, need = self.underpowered
            return (
                f"gate: robust-z heuristic — the calibration band for this detector has {have} "
                f"scores but {need} are needed to decide {self.scores.size} unit(s) at this --fpr; "
                f"calibrate on more known-good episodes to use the conformal gate"
            )
        return "gate: robust-z heuristic, self-calibrated (no calibration band for this detector/embodiment)"

    def evidence_metrics(self) -> dict[str, float]:
        """Gate-related numbers to merge into ``Evidence.metrics``."""
        out = {"robust_z": float(self.robust_z[self.worst]) if self.robust_z.size else 0.0}
        if self.method is GateMethod.CONFORMAL_FDR:
            out["conformal_p"] = float(self.pvalues[self.worst]) if self.pvalues.size else 1.0
            out["reference_n"] = float(self.reference_n)
        return out

    def evidence_thresholds(self) -> dict[str, float]:
        """Gate-related thresholds to merge into ``Evidence.thresholds``."""
        if self.method is GateMethod.CONFORMAL_FDR:
            return {"fdr_q": self.cut if self.cut > 0 else 0.0}
        return {"robust_z": self.cut}


def required_band_size(n_units: int, fpr: float) -> int:
    """Reference scores needed for BH to be able to reject one of ``n_units`` at ``fpr``.

    ``n ≥ m/q − 1``, from requiring the minimum attainable conformal p-value ``1/(n+1)`` to
    reach BH's first rung ``q/m``. Exposed so ``bohrin calibrate`` can tell a user how much
    more known-good data a usable band needs, rather than leaving them to discover that their
    corpus is inert.
    """
    if n_units <= 0 or not 0.0 < fpr < 1.0:
        return 0
    return int(np.ceil(n_units / fpr)) - 1


def _empty(method: GateMethod, cut: float) -> GateResult:
    empty_f = np.empty(0, dtype=np.float64)
    return GateResult(
        method=method,
        flagged=(),
        confidence=empty_f,
        pvalues=empty_f,
        robust_z=empty_f,
        scores=empty_f,
        cut=cut,
        reference_n=0,
    )


def gate(
    scores: FloatArray,
    *,
    fpr: float,
    detector_id: str,
    fallback_z: float,
    corpus: CalibrationCorpus | None = None,
    embodiment: str | None = None,
    eligible: BoolArray | None = None,
) -> GateResult:
    """Select the anomalous units among ``scores`` (higher score ⇒ more anomalous).

    ``eligible`` is an optional per-unit mask of units the detector considers *practically*
    significant (its effect-size floor). Units outside it are never flagged, but they still
    contribute to the score distribution, which is what a robust baseline needs.
    """
    s = np.asarray(scores, dtype=np.float64).ravel()
    if s.size == 0:
        return _empty(GateMethod.ROBUST_Z, fallback_z)

    band = corpus.resolve(detector_id, embodiment) if corpus is not None else None
    calibrator = ConformalCalibrator(fpr)
    z = mad_scores(s)

    # A band that cannot resolve a small enough p-value can never reject; using it anyway
    # would convert "not enough calibration data" into a silent all-clear.
    underpowered: tuple[int, int] | None = None
    if band is not None:
        needed = required_band_size(int(s.size), fpr)
        if int(band.size) < needed:
            underpowered = (int(band.size), needed)
            band = None

    if band is not None:
        calibrated = calibrator.calibrate(s, calibration=band, selection=Selection.FDR_BH)
        selected = calibrated.is_anomaly
        # The BH cutoff, recovered as the largest p-value actually rejected.
        cut = float(np.max(calibrated.pvalues[selected])) if selected.any() else 0.0
        method, reference_n = GateMethod.CONFORMAL_FDR, int(band.size)
        pvalues, confidence = calibrated.pvalues, calibrated.confidence
    else:
        # Self-calibrated confidence, robust-z gate — the shipped heuristic, unchanged.
        calibrated = calibrator.calibrate(s)
        selected = z > fallback_z
        cut, method, reference_n = fallback_z, GateMethod.ROBUST_Z, 0
        pvalues, confidence = calibrated.pvalues, calibrated.confidence

    if eligible is not None:
        mask = np.asarray(eligible, dtype=np.bool_).ravel()
        if mask.shape == selected.shape:
            selected = selected & mask

    # Most-anomalous first, with the index as a stable tie-break so a run is reproducible.
    order = sorted(np.flatnonzero(selected).tolist(), key=lambda i: (-s[i], i))
    return GateResult(
        method=method,
        flagged=tuple(int(i) for i in order),
        confidence=confidence,
        pvalues=pvalues,
        robust_z=z,
        scores=s,
        cut=cut,
        reference_n=reference_n,
        underpowered=underpowered,
    )
