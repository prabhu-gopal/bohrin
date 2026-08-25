"""Family L — CAUSAL SHORTCUTS: does the data invite the policy to cheat? (docs/04 §L).

Catches an imitation-learning-specific pathology invisible to loss curves: the data lets
the model learn the wrong cause. ``causal.copycat_shortcut`` measures how predictable the
current action is from the *previous* action alone — the copycat / causal-confusion
shortcut (de Haan, Jayaraman & Levine, NeurIPS 2019, arXiv 1905.11979).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np

from bohrin._arrays import FloatArray
from bohrin.analysis.robust import keep_finite_rows
from bohrin.detectors._common import blast_over, dataset_provenance, make_finding
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.ir.episode import Episode
from bohrin.ir.schema import ActionSpace, Family, Severity
from bohrin.profile.action_space import action_increments, resolve_action_space
from bohrin.report.model import Evidence, Finding


class CopycatShortcutDetector(Detector):
    """Flags datasets where the action is near-perfectly predictable from the previous action."""

    id = "causal.copycat_shortcut"
    family = Family.CAUSAL
    requires = Requirements(min_episodes=2)
    description = (
        "Detects strong action autocorrelation that invites the copycat/causal-confusion "
        "shortcut — a policy that latches onto its last action and fails under distribution shift."
    )

    _R2 = 0.9  # actions ≥ 90% predictable from the previous action is a copycat risk

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        space = resolve_action_space(ctx.profile, ctx.schema.action_space)
        prev, curr = _previous_current_pairs(ctx.episodes, space)
        if prev.shape[0] < 32:
            return []
        r2 = _linear_r2(prev, curr)
        if r2 < self._R2:
            return []
        severity = Severity.HIGH if r2 >= 0.97 else Severity.MEDIUM
        return [
            make_finding(
                self,
                severity=severity,
                confidence=float(min(1.0, (r2 - self._R2) / (1.0 - self._R2))),
                title=f"Actions are {r2 * 100:.0f}% predictable from the previous action alone",
                mechanism=(
                    "Strong action autocorrelation invites the copycat shortcut: a cloned "
                    "policy can latch onto its last action as a spurious cause (causal "
                    "confusion). Loss stays low in training and it only fails at rollout under "
                    "distribution shift (de Haan et al., NeurIPS 2019)."
                ),
                fix_text=(
                    "Consider action differencing, history dropout, or lower control-rate "
                    "labeling to break the trivial previous-action correlation."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(metrics={"prev_action_r2": r2}, thresholds={"r2": self._R2}),
                blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes),
            )
        ]


class ProprioShortcutDetector(Detector):
    """Flags actions that are near-deterministic in current proprioception.

    A documented shortcut-learning route: the policy learns action = f(proprio) rather than
    the task, then breaks when the deployment proprioception distribution differs at all
    from the demonstrations.
    """

    id = "causal.proprio_shortcut"
    family = Family.CAUSAL
    requires = Requirements(needs_proprio=True, min_episodes=2)
    description = (
        "Detects actions almost fully predictable from current proprioception — a shortcut "
        "that breaks under proprioception shift at deployment."
    )

    _R2 = 0.95

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        # Absolute targets satisfy a_t ≈ o_t by definition, so the raw action would be
        # "predictable from proprioception" on every correctly-recorded pose dataset.
        space = resolve_action_space(ctx.profile, ctx.schema.action_space)
        states: list[FloatArray] = []
        actions: list[FloatArray] = []
        for ep in ctx.episodes:
            proprio = ep.steps.proprio
            if proprio is None:
                continue
            s = np.asarray(proprio, dtype=np.float64)
            a = action_increments(np.asarray(ep.steps.action, dtype=np.float64), space)
            if s.shape[0] != a.shape[0]:
                continue
            states.append(s)
            actions.append(a)
        if not states:
            return []
        width_s = min(x.shape[1] for x in states)
        width_a = min(x.shape[1] for x in actions)
        x = np.vstack([s[:, :width_s] for s in states])
        y = np.vstack([a[:, :width_a] for a in actions])
        if x.shape[0] < 32:
            return []
        r2 = _linear_r2(x, y)
        if r2 < self._R2:
            return []
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=float(min(1.0, (r2 - self._R2) / (1.0 - self._R2))),
                title=f"Actions are {r2 * 100:.0f}% predictable from proprioception alone",
                mechanism=(
                    "The action is nearly a deterministic function of the current joint state. "
                    "A policy can satisfy the training loss by learning that mapping instead of "
                    "the task, and it will break as soon as deployment proprioception differs "
                    "from the demonstrations."
                ),
                fix_text=(
                    "Vary the starting configurations so the same state maps to different "
                    "actions, and verify the policy actually uses its visual input."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(metrics={"proprio_r2": r2}, thresholds={"r2": self._R2}),
                blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes),
            )
        ]


def _previous_current_pairs(
    episodes: Sequence[Episode], space: ActionSpace = ActionSpace.UNKNOWN
) -> tuple[FloatArray, FloatArray]:
    """Stack (previous action, current action) pairs within each episode (no cross-boundary).

    Absolute action spaces are differenced first (see :func:`action_increments`): a smooth pose
    trajectory is trivially predictable from its own previous value, so without this the check
    reports a copycat shortcut on every ``JOINT_POS`` dataset.
    """
    prevs: list[FloatArray] = []
    currs: list[FloatArray] = []
    for ep in episodes:
        action = action_increments(np.asarray(ep.steps.action, dtype=np.float64), space)
        if action.shape[0] < 2:
            continue
        prevs.append(action[:-1])
        currs.append(action[1:])
    if not prevs:
        empty = np.empty((0, 0), dtype=np.float64)
        return empty, empty
    return np.vstack(prevs), np.vstack(currs)


def _linear_r2(features: FloatArray, targets: FloatArray) -> float:
    """Ordinary-least-squares R² for predicting ``targets`` from ``features`` (+ bias).

    Non-finite rows are dropped first: ``lstsq`` raises on NaN/inf, which used to take down the
    whole scan on any dataset containing a NaN (see :func:`keep_finite_rows`).
    """
    features, targets = keep_finite_rows(features, targets)
    if features.shape[0] < 2 or features.size == 0:
        return 0.0
    x = np.hstack([features, np.ones((features.shape[0], 1), dtype=np.float64)])
    coef, _, _, _ = np.linalg.lstsq(x, targets, rcond=None)
    if not np.all(np.isfinite(coef)):
        # A degenerate fit (too few rows, collinear columns) can return non-finite
        # coefficients; that varies by numpy/LAPACK version rather than being reliably
        # raised, so it has to be checked rather than caught. No fit means no explanatory
        # power, which R² = 0 says correctly.
        return 0.0
    # `coef` is finite but an ill-conditioned fit can still make it astronomically large, and
    # multiplying that back through `x` can overflow to inf even though every input was finite
    # — the failure mode this whole function exists to survive, just one step later than the
    # coefficients themselves. Compute under a local errstate (a non-finite result is handled
    # explicitly below, so a warning here would be redundant, not informative) and let the
    # final finiteness check be the single source of truth for "this fit is unusable."
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        pred = x @ coef
        ss_res = float(np.sum((targets - pred) ** 2))
        ss_tot = float(np.sum((targets - targets.mean(axis=0)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    return r2 if np.isfinite(r2) else 0.0
