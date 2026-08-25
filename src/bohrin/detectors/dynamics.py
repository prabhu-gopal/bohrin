"""Family K — DYNAMICS CONSISTENCY: are the transitions physically coherent? (docs/04 §K).

A light, cross-validated dynamics model turns "this transition looks weird" into a
principled residual. This is the *model-based* upgrade to the heuristic
``temporal.action_observation_lag`` and ``smoothness.discontinuity_jump``: a single learned
notion of "physically coherent" that subsumes much of the hand-written geometry.

Gating goes through the shared calibrated gate (:mod:`bohrin.calibrate.gate`) over the
out-of-fold residuals, so a dataset whose dynamics are simply *hard to fit* (uniformly high
residual) produces no finding — only transitions inconsistent **relative to a reference**
are flagged. That reference is a known-good calibration band when one is available and the
dataset's own bulk otherwise.

The ``relative`` criterion is deliberately kept *outside* the statistical gate: a residual as
large as the signal itself is unexplainable on physical grounds regardless of how the rest of
the dataset is distributed, so it is an independent escape hatch rather than a threshold.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from bohrin._arrays import BoolArray, FloatArray
from bohrin.calibrate.dynamics_model import DynamicsFit, fit_forward_dynamics, fit_inverse_dynamics
from bohrin.detectors._common import blast_over, dataset_provenance, gate_scores, make_finding
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.ir.schema import Family, Severity
from bohrin.report.model import Evidence, Finding, Locus

_RESIDUAL_Z = 8.0  # robust-z above which a transition is dynamically inconsistent
_RELATIVE = 1.0  # residual as large as the signal itself ⇒ unexplainable, whatever the spread

# How much of the dataset has to be affected before the finding is worth its ceiling
# severity. An outlier gate on a continuous residual finds a tail on *any* dataset — that is
# what an outlier gate does — so "some transitions are in the tail" cannot by itself be HIGH.
#
# Measured on 20 public LeRobot datasets (scripts/hub_smoke.py): this detector fired at HIGH
# on 19 of them, with flagged fractions spanning 0.94 % to 80.8 % — all reported identically.
# A HIGH that fires on 95 % of curated public data carries no information and would break
# `--fail-on HIGH` for every user. The flagged rate is already treated as the honest blast
# radius below; it has to move the severity for the same reason.
_HIGH_FRAC = 0.20
_MEDIUM_FRAC = 0.05


def _scaled_severity(ceiling: Severity, frac: float, *, unexplainable: bool) -> Severity:
    """Step ``ceiling`` down when the defect is too diffuse to deserve it.

    Two independent routes to the ceiling, because two different things are serious:

    * **Extent** — a large share of transitions is affected, so the dataset is broadly wrong.
    * **Magnitude** — at least one transition has a residual as large as the signal itself.
      That is not a distribution tail, it is physically unexplainable: a teleport, a dropped
      segment, a corrupt action. One of those is worth a HIGH however rare it is, and
      scaling purely on extent would quietly downgrade the single worst defect in the file.

    ``ceiling`` is what this detector reports when either route is taken; neither ever
    escalates past it.
    """
    if unexplainable or frac >= _HIGH_FRAC:
        return ceiling
    floor = Severity.MEDIUM if frac >= _MEDIUM_FRAC else Severity.LOW
    return floor if floor.rank < ceiling.rank else ceiling


def _rate(mask: BoolArray) -> str:
    """The flagged share of transitions, rendered so small diffuse rates stay legible."""
    frac = float(mask.sum()) / float(mask.size) if mask.size else 0.0
    return f"{frac:.2%}" if frac < 0.01 else f"{frac:.1%}"


def _report(
    detector: Detector,
    ctx: AnalysisContext,
    fit: DynamicsFit,
    *,
    severity: Severity,  # the *ceiling*; _scaled_severity steps it down for diffuse defects
    title: str,
    mechanism: str,
    fix_text: str,
) -> list[Finding]:
    # Two complementary criteria: an outlier relative to the reference distribution (the
    # calibrated gate), OR a residual as large as the signal itself (which survives a
    # degenerate, near-perfect fit where every residual is tiny and none is an outlier).
    decision = gate_scores(ctx, detector, fit.residuals, fallback_z=_RESIDUAL_Z)
    relative = fit.relative
    mask = np.zeros(fit.residuals.shape, dtype=np.bool_)
    mask[list(decision.flagged)] = True
    mask |= relative > _RELATIVE
    if not mask.any():
        return []
    frac_steps = float(mask.sum()) / float(mask.size) if mask.size else 0.0
    owners = np.unique(fit.owner[mask])
    ep_ids = [ctx.episodes[int(i)].episode_id for i in owners if int(i) < len(ctx.episodes)]
    worst = int(np.argmax(fit.residuals))
    return [
        make_finding(
            detector,
            severity=_scaled_severity(severity, frac_steps, unexplainable=bool((relative > _RELATIVE).any())),
            confidence=float(decision.confidence[worst]) if decision.confidence.size else 0.0,
            # Lead with the transition rate, because that is what was actually measured. Naming
            # only the episode count overstates a diffuse defect: a 2 %-of-transitions rate lands
            # in nearly every episode, and "in 206 episode(s)" then reads as though 206 episodes
            # were ruined when no single one was.
            title=title.format(n=len(ep_ids), pct=_rate(mask)),
            mechanism=mechanism,
            fix_text=fix_text,
            provenance=dataset_provenance(ctx),
            evidence=Evidence(
                metrics={
                    "max_residual": float(fit.residuals[worst]),
                    "max_relative_residual": float(relative[worst]),
                    "n_bad_transitions": float(int(mask.sum())),
                    "model_r2": fit.r2,
                    **decision.evidence_metrics(),
                },
                thresholds={**decision.evidence_thresholds(), "relative": _RELATIVE},
                notes=decision.note(),
            ),
            locus=Locus(episodes=ep_ids[:50]),
            # The detection unit here is one transition, so the step fraction is the honest
            # extent: a diffuse 2 %-of-transitions rate touches nearly every episode without
            # ruining any of them, and the episode count alone cannot express that.
            blast=blast_over(
                len(ep_ids),
                ctx.profile.n_episodes,
                frac_steps=frac_steps,
            ),
        )
    ]


class InverseResidualDetector(Detector):
    """Flags transitions where the logged action does not explain the observed state change."""

    id = "dynamics.inverse_residual"
    family = Family.DYNAMICS
    requires = Requirements(needs_proprio=True, min_episodes=4)
    description = (
        "Fits an inverse dynamics model g(oₜ, oₜ₊₁) → âₜ and flags transitions whose residual "
        "shows the logged action doesn't explain the observed motion."
    )

    def score_units(self, ctx: AnalysisContext) -> FloatArray | None:
        """Per-transition inverse-dynamics residual — the quantity :meth:`run` gates on."""
        fit = fit_inverse_dynamics(ctx.episodes)
        return fit.residuals if fit is not None else None

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        fit = fit_inverse_dynamics(ctx.episodes)
        if fit is None:
            return []
        return _report(
            self,
            ctx,
            fit,
            severity=Severity.HIGH,
            title="Logged actions don't explain {pct} of transitions, spread over {n} episode(s)",
            mechanism=(
                "An inverse dynamics model reconstructs the action that must have produced each "
                "observed state change. Where the residual is large, the recorded action is "
                "inconsistent with the physics of the transition — corrupt or mislabeled actions, "
                "an action/observation misalignment, or an impossible jump. Training on these "
                "teaches a broken dynamics map."
            ),
            fix_text=(
                "Inspect the flagged episodes for recording misalignment or dropped frames; "
                "re-sync the action and observation streams."
            ),
        )


class ForwardResidualDetector(Detector):
    """Flags transitions where the state evolves inconsistently with the action taken."""

    id = "dynamics.forward_residual"
    family = Family.DYNAMICS
    requires = Requirements(needs_proprio=True, min_episodes=4)
    description = (
        "Fits a forward dynamics model f(oₜ, aₜ) → ôₜ₊₁ and flags steps where the state "
        "evolves inconsistently with the action taken."
    )

    def score_units(self, ctx: AnalysisContext) -> FloatArray | None:
        """Per-transition forward-dynamics residual — the quantity :meth:`run` gates on."""
        fit = fit_forward_dynamics(ctx.episodes)
        return fit.residuals if fit is not None else None

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        fit = fit_forward_dynamics(ctx.episodes)
        if fit is None:
            return []
        return _report(
            self,
            ctx,
            fit,
            severity=Severity.MEDIUM,
            title="State evolves inconsistently with the actions in {pct} of transitions ({n} episodes)",
            mechanism=(
                "A forward dynamics model predicts the next state from the current state and "
                "action. Where the prediction diverges sharply, the segment is physically "
                "inconsistent — typically dropped frames or a mid-episode reset."
            ),
            fix_text="Inspect the flagged segments; drop episodes containing resets or frame drops.",
        )
