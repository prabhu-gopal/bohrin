"""Family C — SMOOTHNESS / KINEMATICS: is the motion learnable? (docs/04 §C).

Jerk is the *Consistency Matters* metric (arXiv 2412.14309); a discontinuity is a
physically-impossible single-step teleport.

**On calibration.** Both detectors emit a per-unit non-conformity score and hand it to the
shared gate (:mod:`bohrin.calibrate.gate`), which selects at FDR ``--fpr`` against a
known-good reference band when the calibration corpus covers this embodiment, and otherwise
falls back to the documented robust-z constant below. Each finding records which of the two
ran, so a calibrated result is never confused with a heuristic one. ``score_units`` exposes
the same score for ``bohrin calibrate`` to collect.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from bohrin._arrays import FloatArray, IntArray
from bohrin.detectors._common import (
    blast_over,
    channel,
    dataset_provenance,
    gate_scores,
    make_finding,
    sparkline,
)
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.ir.schema import Family, Severity
from bohrin.report.model import Evidence, Finding, Locus

_JERK_Z = 3.5  # robust-z above which an episode's jerk is a genuine outlier
_JUMP_Z = 10.0  # robust-z above which a single-step displacement is a teleport


class JerkOutlierDetector(Detector):
    """Ranks episodes by jerk (3rd-derivative energy) and flags robust outliers."""

    id = "smoothness.jerk_outlier"
    family = Family.SMOOTHNESS
    requires = Requirements(min_episodes=8)
    description = "Flags shaky/jerky demonstrations; jittery teleop teaches the policy to tremble."

    def score_units(self, ctx: AnalysisContext) -> FloatArray | None:
        """Per-episode jerk energy — the quantity :meth:`run` gates on."""
        hz = ctx.profile.control_hz or 1.0
        if not ctx.episodes:
            return None
        return np.array([_jerk_energy(channel(ep, prefer_proprio=True), hz) for ep in ctx.episodes])

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        episodes = ctx.episodes
        if len(episodes) < self.requires.min_episodes:
            return []
        scores = self.score_units(ctx)
        if scores is None:
            return []
        decision = gate_scores(ctx, self, scores, fallback_z=_JERK_Z)
        if not decision.fired:
            return []
        flagged = list(decision.flagged)
        ep_ids = [episodes[i].episode_id for i in flagged]
        median = float(np.median(scores)) or 1.0
        worst = decision.worst
        ratio = float(scores[worst] / median) if median else 0.0
        return [
            make_finding(
                self,
                severity=Severity.HIGH if len(flagged) > 0.2 * len(episodes) else Severity.MEDIUM,
                confidence=decision.worst_confidence,
                title=f"Shaky teleoperation in {len(flagged)} episode(s) (up to {ratio:.1f}× median jerk)",
                mechanism=(
                    "Jittery teleoperation teaches the policy to tremble; high-frequency "
                    "action noise is unlearnable by an MSE head and hurts smooth control."
                ),
                fix_text="Re-record or smooth the flagged episodes; consider a low-pass filter on teleop input.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "jerk_ratio": ratio,
                        "n_flagged": float(len(flagged)),
                        **decision.evidence_metrics(),
                    },
                    thresholds=decision.evidence_thresholds(),
                    notes=decision.note(),
                    # Per-episode jerk energy: the flagged episodes stand out as spikes.
                    series=sparkline(scores),
                    series_label="jerk energy per episode (flagged episodes are the spikes)",
                ),
                locus=Locus(episodes=ep_ids[:50]),
                blast=blast_over(len(flagged), ctx.profile.n_episodes),
            )
        ]


class DiscontinuityJumpDetector(Detector):
    """Flags single-step teleports — physically impossible per-dt displacements."""

    id = "smoothness.discontinuity_jump"
    family = Family.SMOOTHNESS
    description = "Detects teleport-like jumps (dropped frames or a mid-episode reset) the model can't learn."

    def _displacements(self, ctx: AnalysisContext) -> tuple[FloatArray, IntArray]:
        """Per-step displacement magnitudes and the episode each step belongs to."""
        disp_blocks: list[FloatArray] = []
        owners: list[IntArray] = []
        for i, ep in enumerate(ctx.episodes):
            traj = channel(ep, prefer_proprio=True)
            if traj.shape[0] < 2:
                continue
            step_norm = np.linalg.norm(np.diff(traj, axis=0), axis=1)
            disp_blocks.append(step_norm)
            owners.append(np.full(step_norm.shape[0], i, dtype=np.int64))
        if not disp_blocks:
            return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.int64)
        return np.concatenate(disp_blocks), np.concatenate(owners)

    def score_units(self, ctx: AnalysisContext) -> FloatArray | None:
        """Per-step displacement magnitude — the quantity :meth:`run` gates on."""
        disp, _ = self._displacements(ctx)
        return disp if disp.size else None

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        episodes = ctx.episodes
        if not episodes:
            return []
        disp, owner = self._displacements(ctx)
        if disp.size == 0:
            return []
        decision = gate_scores(ctx, self, disp, fallback_z=_JUMP_Z)
        if not decision.fired:
            return []
        jump_mask = np.zeros(disp.shape, dtype=np.bool_)
        jump_mask[list(decision.flagged)] = True
        jump_owner_ids = np.unique(owner[jump_mask])
        ep_ids = [episodes[int(i)].episode_id for i in jump_owner_ids]
        worst = decision.worst
        return [
            make_finding(
                self,
                severity=Severity.HIGH,
                confidence=decision.worst_confidence,
                title=f"Teleport-like jumps in {len(ep_ids)} episode(s)",
                mechanism=(
                    "A single-step jump far beyond a physically plausible displacement is a "
                    "dropped-frame stitch or a mid-episode reset — an impossible transition "
                    "the model can't learn, and it breaks action-chunk continuity."
                ),
                fix_text="Inspect the flagged steps; drop episodes with frame drops or splice errors.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "max_jump": float(disp[worst]),
                        "n_jump_steps": float(len(decision.flagged)),
                        **decision.evidence_metrics(),
                    },
                    thresholds=decision.evidence_thresholds(),
                    notes=decision.note(),
                    # Per-step displacement around the worst jump — the teleport is visible
                    # as a single spike against an otherwise smooth band.
                    series=sparkline(disp[max(0, worst - 200) : worst + 200]),
                    series_label="per-step displacement around the worst jump",
                ),
                locus=Locus(episodes=ep_ids[:50]),
                blast=blast_over(len(ep_ids), ctx.profile.n_episodes),
            )
        ]


def _jerk_energy(traj: FloatArray, hz: float) -> float:
    """Mean squared third finite difference (jerk), scaled by control frequency."""
    if traj.shape[0] < 4:
        return 0.0
    dt = 1.0 / hz if hz > 0 else 1.0
    jerk = np.diff(traj, n=3, axis=0) / (dt**3)
    return float(np.mean(np.sum(jerk**2, axis=1)))
