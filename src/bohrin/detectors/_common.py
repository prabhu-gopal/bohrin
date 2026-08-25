"""Shared helpers for the detector battery.

Small, well-tested primitives the family modules reuse: dataset-level provenance, a
finding constructor that fills ``detector_id``/``family`` from the detector, robust
(MAD-based) statistics, and pooling of per-step signals across a reservoir of episodes.
Keeping these here avoids copy-paste drift between the ~14 detectors.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from bohrin._arrays import BoolArray, FloatArray, IntArray
from bohrin.analysis.robust import mad_scores
from bohrin.calibrate.gate import GateResult
from bohrin.calibrate.gate import gate as _gate
from bohrin.detectors.base import AnalysisContext, Detector
from bohrin.ir.episode import Episode
from bohrin.ir.schema import Provenance, Severity
from bohrin.report.model import BlastRadius, Evidence, Finding, Fix, Locus

_EPS = 1e-12

# Re-exported so the whole battery keeps importing its robust statistics from one place;
# the implementation lives in ``analysis`` because the calibration gate needs it too.
__all__ = [
    "SERIES_POINTS",
    "blast_over",
    "channel",
    "dataset_provenance",
    "gate_scores",
    "mad_scores",
    "make_finding",
    "pool_steps",
    "sparkline",
]


def dataset_provenance(ctx: AnalysisContext, *, locator: str = "all episodes") -> Provenance:
    """Dataset-level provenance for a finding that spans the dataset."""
    if ctx.episodes:
        return ctx.episodes[0].source.model_copy(update={"locator": locator})
    return Provenance(adapter="unknown", uri=ctx.config.path, locator=locator)


def make_finding(
    detector: Detector,
    *,
    severity: Severity,
    confidence: float,
    title: str,
    mechanism: str,
    fix_text: str,
    provenance: Provenance,
    evidence: Evidence | None = None,
    locus: Locus | None = None,
    blast: BlastRadius | None = None,
    fix_machine: dict[str, object] | None = None,
) -> Finding:
    """Build a :class:`Finding`, filling id/family from ``detector``."""
    return Finding(
        detector_id=detector.id,
        family=detector.family,
        severity=severity,
        confidence=max(0.0, min(1.0, confidence)),
        title=title,
        mechanism=mechanism,
        evidence=evidence or Evidence(),
        locus=locus or Locus(),
        blast_radius=blast or BlastRadius(),
        fix=Fix(text=fix_text, machine=fix_machine or {}),
        provenance=provenance,
    )


def blast_over(n_episodes: int, total_episodes: int, frac_steps: float = 0.0) -> BlastRadius:
    """A :class:`BlastRadius` helper."""
    return BlastRadius(
        n_episodes=n_episodes,
        total_episodes=total_episodes,
        frac_steps=float(frac_steps),
    )


def gate_scores(
    ctx: AnalysisContext,
    detector: Detector,
    scores: FloatArray,
    *,
    fallback_z: float,
    eligible: BoolArray | None = None,
) -> GateResult:
    """Gate ``scores`` for ``detector``, using the calibration corpus when it covers them.

    The detector-facing wrapper over :func:`bohrin.calibrate.gate.gate`: it supplies the
    corpus, the dataset's embodiment (the Mondrian category) and ``--fpr`` from the context,
    so a detector never has to know how calibration is resolved. Pass the detector's own
    effect-size floor as ``eligible``.
    """
    return _gate(
        scores,
        fpr=ctx.config.fpr,
        detector_id=detector.id,
        fallback_z=fallback_z,
        corpus=ctx.corpus,
        embodiment=ctx.schema.embodiment,
        eligible=eligible,
    )


#: Maximum points kept in ``Evidence.series``. Enough to render a legible sparkline,
#: small enough that a report with many findings stays a lightweight JSON document.
SERIES_POINTS = 160


def sparkline(values: FloatArray | Sequence[float], *, points: int = SERIES_POINTS) -> list[float]:
    """Downsample a 1-D signal to at most ``points`` values for :attr:`Evidence.series`.

    Uses evenly spaced *index* selection rather than averaging: a mean-pooled series would
    smooth away the single-frame spike that a jerk or discontinuity finding is *about*,
    which would make the picture disagree with the number beside it.
    """
    x = np.asarray(values, dtype=np.float64).ravel()
    x = x[np.isfinite(x)]
    if x.size == 0:
        return []
    if x.size > points:
        idx = np.linspace(0, x.size - 1, points).round().astype(np.int64)
        x = x[idx]
    return [float(v) for v in x]


def channel(episode: Episode, *, prefer_proprio: bool) -> FloatArray:
    """The trajectory used for kinematics: proprio if available and preferred, else action."""
    steps = episode.steps
    if prefer_proprio and steps.proprio is not None:
        return np.asarray(steps.proprio, dtype=np.float64)
    return np.asarray(steps.action, dtype=np.float64)


def pool_steps(
    episodes: Sequence[Episode],
    *,
    attr: str,
) -> tuple[FloatArray, IntArray]:
    """Stack a per-step column across episodes.

    Returns ``(rows, episode_index)`` where ``rows`` is ``(sum T_i, D)`` and
    ``episode_index[k]`` is the reservoir index of the episode row ``k`` came from.
    """
    blocks: list[FloatArray] = []
    owners: list[IntArray] = []
    for i, ep in enumerate(episodes):
        col = getattr(ep.steps, attr)
        if col is None:
            continue
        arr = np.asarray(col, dtype=np.float64)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        blocks.append(arr)
        owners.append(np.full(arr.shape[0], i, dtype=np.int64))
    if not blocks:
        return np.empty((0, 0), dtype=np.float64), np.empty(0, dtype=np.int64)
    return np.vstack(blocks), np.concatenate(owners)
