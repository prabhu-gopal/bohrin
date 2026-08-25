"""Remaining SMOOTHNESS and TEMPORAL checks (docs/04 §C, §D; docs/06 P3).

Four checks that were catalogued in P1 but only earn their place once the report is dense
enough to rank them properly: path efficiency, curvature, gripper chatter, and the
non-Markovian pause. All four are *shape* properties of a trajectory, so they share the
robust-z gating and effect-size floors the rest of the battery uses.

The pause check is the interesting one: it is the only detector in this module whose
severity is **policy-dependent**, because "the same state maps to two different actions"
is fatal for a single-step BC head and completely fine for ACT or Diffusion.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from bohrin._arrays import BoolArray, FloatArray
from bohrin.detectors._common import (
    blast_over,
    channel,
    dataset_provenance,
    gate_scores,
    make_finding,
    sparkline,
)
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.ir.episode import Episode
from bohrin.ir.schema import Family, PolicyFamily, Severity
from bohrin.report.model import Evidence, Finding, Locus

_EPS = 1e-12

#: A trajectory this many times longer than the straight-line distance is wandering.
#: Deliberately generous: real manipulation goes around obstacles, so a merely indirect
#: path is normal and only a gross detour is worth a user's attention.
_PATH_RATIO = 2.5
_PATH_Z = 3.5
#: A wandering episode must also be this many times less direct than the dataset's own
#: median. Without it, an inherently circuitous task flags all of its episodes.
_PATH_RELATIVE = 1.8
#: Episodes whose net displacement is below this fraction of the dataset median are
#: excluded: the efficiency ratio divides by that displacement and is meaningless when it
#: approaches zero (this exact case produced a false HIGH on clean data).
_MIN_DIRECT_FRAC = 0.5
#: Curvature is scale-free but noisy; require both a robust-z outlier and this floor.
#: Smoothing window (steps) applied before measuring curvature -- see _mean_curvature.
_CURVATURE_SMOOTH = 5
_CURVATURE_Z = 3.5
_CURVATURE_FLOOR = 1.0
#: Gripper toggles per second above this rate are chatter, not intentional regrasping.
_CHATTER_HZ = 2.0
_MIN_TOGGLES = 6
#: Two visits to the "same" state count as a revisit within this fraction of the state's
#: own spread. Relative, so it transfers across embodiments and units.
_STATE_TOL = 0.02
#: The subsequent actions must disagree by at least this fraction of the action spread.
_ACTION_DISAGREE = 0.5
_MIN_PAUSE_EPISODES = 3


def _path_efficiency(traj: FloatArray) -> float:
    """Travelled distance ÷ straight-line distance. 1.0 is a perfectly direct path."""
    if traj.shape[0] < 2:
        return 1.0
    travelled = float(np.sum(np.linalg.norm(np.diff(traj, axis=0), axis=1)))
    direct = float(np.linalg.norm(traj[-1] - traj[0]))
    if direct < _EPS:
        return 1.0  # a closed loop has no meaningful ratio; never call it inefficient
    return travelled / direct


def _direct_distance(traj: FloatArray) -> float:
    """Straight-line distance from an episode's first state to its last."""
    if traj.shape[0] < 2:
        return 0.0
    return float(np.linalg.norm(traj[-1] - traj[0]))


def _smooth(traj: FloatArray, window: int) -> FloatArray:
    """Centered moving average along time — a zero-phase low-pass, no SciPy needed."""
    if window <= 1 or traj.shape[0] <= window:
        return traj
    kernel = np.ones(window, dtype=np.float64) / window
    padded = np.pad(traj, ((window // 2, window // 2), (0, 0)), mode="edge")
    return np.stack(
        [np.convolve(padded[:, d], kernel, mode="valid")[: traj.shape[0]] for d in range(traj.shape[1])], axis=1
    )


def _mean_curvature(traj: FloatArray) -> float:
    """Mean discrete curvature ``‖ẋ × ẍ‖ / ‖ẋ‖³``, generalized to n-D.

    In n dimensions the cross product is replaced by the component of the acceleration
    orthogonal to the velocity, which equals the cross-product magnitude in 3-D and keeps
    the quantity meaningful for 6- or 7-D joint trajectories.

    **Computed on a smoothed trajectory, and that is not a detail.** Curvature divides by
    speed cubed, so on raw data it is dominated by per-step sensor noise: measured on the
    clean fixture, raw curvature scored ~25 for ordinary trajectories and ~0.06 for a
    deliberately erratic one — the metric was reporting jitter, and reporting it backwards.
    Smoothing first makes it measure the *path shape* it is supposed to measure. High-
    frequency jitter is already owned by ``smoothness.jerk_outlier``.
    """
    traj = _smooth(traj, _CURVATURE_SMOOTH)
    if traj.shape[0] < 3:
        return 0.0
    velocity = np.diff(traj, axis=0)
    acceleration = np.diff(velocity, axis=0)
    v = velocity[:-1]
    speed = np.linalg.norm(v, axis=1)
    usable = speed > _EPS
    if not usable.any():
        return 0.0
    v_u = v[usable]
    a_u = acceleration[usable]
    s_u = speed[usable]
    unit = v_u / s_u[:, None]
    parallel = np.sum(a_u * unit, axis=1)[:, None] * unit
    orthogonal = np.linalg.norm(a_u - parallel, axis=1)
    return float(np.mean(orthogonal / (s_u**2 + _EPS)))


class PathEfficiencyDetector(Detector):
    """Flags wandering demonstrations — far more travel than the task requires."""

    id = "smoothness.path_efficiency"
    family = Family.SMOOTHNESS
    requires = Requirements(min_episodes=8)
    description = "Detects circuitous demos that encode unnecessary motion the policy will imitate."

    def _ratios_and_eligibility(self, ctx: AnalysisContext) -> tuple[FloatArray, BoolArray, float]:
        """Per-episode path-efficiency ratios, which are judgeable, and the baseline ratio.

        The ratio's denominator is the straight-line distance, so an episode that happens to
        end near where it started produces an enormous ratio by division alone. Those
        episodes are not wandering — the metric is simply undefined for them, and including
        them manufactured a false HIGH on clean data. Only episodes whose displacement is
        comparable to the dataset's own typical displacement are eligible to be flagged.
        """
        trajectories = [channel(ep, prefer_proprio=True) for ep in ctx.episodes]
        ratios = np.array([_path_efficiency(t) for t in trajectories])
        direct = np.array([_direct_distance(t) for t in trajectories])
        median_direct = float(np.median(direct)) if direct.size else 0.0
        comparable: BoolArray = (
            direct >= _MIN_DIRECT_FRAC * median_direct if median_direct > _EPS else np.zeros(direct.shape, dtype=bool)
        )
        baseline = float(np.median(ratios[comparable])) if comparable.any() else 0.0
        return ratios, comparable, baseline

    def score_units(self, ctx: AnalysisContext) -> FloatArray | None:
        """Path-efficiency ratio per *judgeable* episode — the quantity :meth:`run` gates on.

        Only the comparable episodes are contributed to a calibration band: the excluded ones
        have an undefined ratio, and letting those into a reference distribution would widen
        it with numbers the gate never tests against.
        """
        if not ctx.episodes:
            return None
        ratios, comparable, _ = self._ratios_and_eligibility(ctx)
        return ratios[comparable] if comparable.any() else None

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        episodes = ctx.episodes
        if len(episodes) < self.requires.min_episodes:
            return []
        ratios, comparable, baseline = self._ratios_and_eligibility(ctx)
        if comparable.sum() < 4:
            return []

        # Judge against the *dataset's own* typical directness: a task that is inherently
        # circuitous should not have every episode flagged. The absolute floor is an
        # effect-size guard, not a statistical one, so it rides along as ``eligible``.
        big_enough: BoolArray = comparable & (ratios > max(_PATH_RATIO, _PATH_RELATIVE * baseline))
        decision = gate_scores(
            ctx,
            self,
            np.where(comparable, ratios, baseline),
            fallback_z=_PATH_Z,
            eligible=big_enough,
        )
        if not decision.fired:
            return []
        flagged = list(decision.flagged)
        worst = decision.worst
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM if len(flagged) > 0.2 * len(episodes) else Severity.LOW,
                confidence=decision.worst_confidence,
                title=(f"{len(flagged)} episode(s) wander: up to {ratios[worst]:.1f}× the direct path"),
                mechanism=(
                    "A demonstration that travels far more than the task requires encodes "
                    "unnecessary motion. The policy imitates the detour, which lengthens "
                    "rollouts and gives compounding error more time to accumulate."
                ),
                fix_text="Review the flagged episodes; re-record the ones where the operator was searching.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "worst_ratio": float(ratios[worst]),
                        "median_ratio": float(np.median(ratios)),
                        "n_flagged": float(len(flagged)),
                        **decision.evidence_metrics(),
                    },
                    thresholds={"ratio": _PATH_RATIO, **decision.evidence_thresholds()},
                    notes=decision.note(),
                    series=sparkline(ratios),
                    series_label="path length ÷ direct distance, per episode",
                ),
                locus=Locus(episodes=[episodes[i].episode_id for i in flagged][:50]),
                blast=blast_over(len(flagged), ctx.profile.n_episodes),
            )
        ]


class CurvatureDetector(Detector):
    """Flags erratic, high-curvature motion that is harder to fit and generalize."""

    id = "smoothness.curvature"
    family = Family.SMOOTHNESS
    requires = Requirements(min_episodes=8)
    description = "Detects erratic high-curvature paths."

    def score_units(self, ctx: AnalysisContext) -> FloatArray | None:
        """Mean smoothed curvature per episode — the quantity :meth:`run` gates on."""
        if not ctx.episodes:
            return None
        curves = np.array([_mean_curvature(channel(ep, prefer_proprio=True)) for ep in ctx.episodes])
        finite: FloatArray = np.nan_to_num(curves, nan=0.0, posinf=0.0, neginf=0.0)
        return finite

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        episodes = ctx.episodes
        if len(episodes) < self.requires.min_episodes:
            return []
        curves = self.score_units(ctx)
        if curves is None:
            return []
        median = float(np.median(curves))
        # The absolute floor keeps a dataset of uniformly gentle paths from having its
        # gentlest-but-highest episode reported as "erratic" — practical, not statistical.
        eligible: BoolArray = curves > max(_CURVATURE_FLOOR, 2.0 * median)
        decision = gate_scores(ctx, self, curves, fallback_z=_CURVATURE_Z, eligible=eligible)
        if not decision.fired:
            return []
        flagged = list(decision.flagged)
        worst = decision.worst
        return [
            make_finding(
                self,
                severity=Severity.LOW,
                confidence=decision.worst_confidence,
                title=f"High path curvature in {len(flagged)} episode(s) — erratic motion",
                mechanism=(
                    "Sharply curving paths are harder to fit than smooth ones and generalize "
                    "worse, because small state errors produce large action differences along "
                    "a tight turn."
                ),
                fix_text="Check the flagged episodes for operator over-correction; smooth or re-record.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "worst_curvature": float(curves[worst]),
                        "median_curvature": median,
                        **decision.evidence_metrics(),
                    },
                    thresholds={"floor": _CURVATURE_FLOOR, **decision.evidence_thresholds()},
                    notes=decision.note(),
                    series=sparkline(curves),
                    series_label="mean curvature per episode",
                ),
                locus=Locus(episodes=[episodes[i].episode_id for i in flagged][:50]),
                blast=blast_over(len(flagged), ctx.profile.n_episodes),
            )
        ]


def _gripper_index(ctx: AnalysisContext) -> int | None:
    """The gripper's action index: declared if the schema says so, else the last channel.

    Falling back to the last channel matches the near-universal convention, but the
    detector only *uses* the fallback when that channel is plausibly binary — otherwise a
    6-DoF arm with no gripper would have its wrist rotation judged as a gripper.
    """
    if ctx.schema.gripper is not None:
        return ctx.schema.gripper.action_index
    stats = ctx.profile.action
    if stats.dim == 0:
        return None
    last = stats.dim - 1
    sample = stats.sample
    if sample.size == 0 or sample.shape[1] <= last:
        return None
    column = sample[:, last]
    lo, hi = float(np.min(column)), float(np.max(column))
    if hi - lo < _EPS:
        return None
    # Plausibly binary: most mass sits at the two extremes.
    spread = hi - lo
    near_ends = np.mean((np.abs(column - lo) < 0.1 * spread) | (np.abs(column - hi) < 0.1 * spread))
    return last if near_ends > 0.8 else None


def _toggles(signal: FloatArray) -> int:
    """Number of open↔close transitions, thresholded at the signal's own midpoint."""
    lo, hi = float(np.min(signal)), float(np.max(signal))
    if hi - lo < _EPS:
        return 0
    binary = signal > (lo + hi) / 2.0
    return int(np.sum(binary[1:] != binary[:-1]))


class GripperChatterDetector(Detector):
    """Flags rapid open/close toggling — teleop chatter that teaches unstable grasping."""

    id = "temporal.gripper_chatter"
    family = Family.TEMPORAL
    description = "Detects gripper chatter (rapid open/close toggles beyond a plausible rate)."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        index = _gripper_index(ctx)
        if index is None or not ctx.episodes:
            return []
        hz = ctx.profile.control_hz or 1.0
        offenders: list[tuple[str, int, float]] = []
        for ep in ctx.episodes:
            action = np.asarray(ep.steps.action, dtype=np.float64)
            if action.shape[1] <= index or action.shape[0] < 2:
                continue
            n = _toggles(action[:, index])
            seconds = action.shape[0] / hz
            rate = n / seconds if seconds > 0 else 0.0
            if n >= _MIN_TOGGLES and rate > _CHATTER_HZ:
                offenders.append((ep.episode_id, n, rate))
        if not offenders:
            return []
        offenders.sort(key=lambda item: -item[2])
        worst_id, worst_n, worst_rate = offenders[0]
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM if len(offenders) > 0.2 * len(ctx.episodes) else Severity.LOW,
                confidence=0.9,
                title=f"Gripper chatter in {len(offenders)} episode(s) (up to {worst_n} toggles)",
                mechanism=(
                    "Rapid open/close toggling is teleoperation noise, not intent. The policy "
                    "learns to flutter the gripper, which drops objects mid-transport and makes "
                    "grasp timing unreliable."
                ),
                fix_text=(
                    "Debounce the gripper input at recording time, or filter the flagged "
                    "episodes; a real regrasp is slow enough to survive a debounce."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "worst_toggles": float(worst_n),
                        "worst_rate_hz": worst_rate,
                        "n_episodes": float(len(offenders)),
                    },
                    thresholds={"rate_hz": _CHATTER_HZ, "min_toggles": float(_MIN_TOGGLES)},
                    notes=f"gripper action index {index}",
                ),
                locus=Locus(episodes=[o[0] for o in offenders][:50], dimensions=[index]),
                blast=blast_over(len(offenders), ctx.profile.n_episodes),
                fix_machine={"action": "debounce_gripper", "dimension": index, "worst": worst_id},
            )
        ]


def _pause_conflicts(episode: Episode, state_tol: float, action_tol: float) -> int:
    """Count revisited states whose *next* actions disagree — the non-Markovian signature.

    Compares each step to later steps that are near-identical in state. If the actions
    taken from those near-identical states differ substantially, a single-step policy
    conditioned on state alone cannot represent both.
    """
    proprio = episode.steps.proprio
    if proprio is None:
        return 0
    state = np.asarray(proprio, dtype=np.float64)
    action = np.asarray(episode.steps.action, dtype=np.float64)
    n = min(state.shape[0], action.shape[0])
    if n < 4:
        return 0
    state, action = state[:n], action[:n]

    conflicts = 0
    # Compare only against *later* steps at a stride, keeping this O(n²/stride) with a
    # small constant — episodes are short, and a full kNN here would dominate the scan.
    stride = max(1, n // 200)
    for i in range(0, n - 1, stride):
        deltas = np.linalg.norm(state[i + 1 :] - state[i], axis=1)
        near = np.flatnonzero(deltas < state_tol)
        if near.size == 0:
            continue
        action_gaps = np.linalg.norm(action[i + 1 + near] - action[i], axis=1)
        if np.any(action_gaps > action_tol):
            conflicts += 1
    return conflicts


class NonMarkovianPauseDetector(Detector):
    """Same state → different next action: a single-step BC head cannot represent this."""

    id = "temporal.non_markovian_pause"
    family = Family.TEMPORAL
    requires = Requirements(needs_proprio=True, min_episodes=4)
    description = "Detects 'wait, then act at the same state' — unlearnable by a single-step BC policy."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        episodes = ctx.episodes
        if len(episodes) < self.requires.min_episodes:
            return []
        state_spread = float(np.median(ctx.profile.proprio.std)) if ctx.profile.proprio else 0.0
        action_spread = float(np.median(ctx.profile.action.std))
        if state_spread <= _EPS or action_spread <= _EPS:
            return []  # degenerate data: every tolerance would be arbitrary

        state_tol = _STATE_TOL * state_spread
        action_tol = _ACTION_DISAGREE * action_spread
        counts = np.array([_pause_conflicts(ep, state_tol, action_tol) for ep in episodes], dtype=np.float64)
        offenders = [i for i in range(len(episodes)) if counts[i] > 0]
        if len(offenders) < _MIN_PAUSE_EPISODES:
            return []

        # Policy-weighted severity: this is fatal for a Markovian head and a non-issue for
        # an architecture that conditions on history or predicts a chunk (docs/04 §D).
        family = ctx.policy.family if ctx.policy else PolicyFamily.UNKNOWN
        if family is PolicyFamily.BC_MLP:
            severity, advice = Severity.HIGH, "Switch to action chunking (ACT) or a Diffusion Policy."
        elif family in (PolicyFamily.ACT, PolicyFamily.DIFFUSION):
            severity, advice = Severity.LOW, "Your target architecture already handles this; no action needed."
        else:
            severity, advice = Severity.MEDIUM, "Prefer action chunking (ACT) or Diffusion Policy over plain BC."

        return [
            make_finding(
                self,
                severity=severity,
                confidence=0.75,
                title=f"Same state, different next action in {len(offenders)} episode(s)",
                mechanism=(
                    "The operator paused and then acted from an almost identical state, so the "
                    "same observation maps to two different actions. A single-step policy "
                    "conditioned on the current state alone cannot represent both, and averages "
                    "them into a motion that matches neither."
                ),
                fix_text=advice,
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "n_episodes": float(len(offenders)),
                        "max_conflicts": float(np.max(counts)),
                    },
                    thresholds={"state_tol": state_tol, "action_tol": action_tol},
                    notes=f"target family: {family.value}",
                    series=sparkline(counts),
                    series_label="conflicting revisits per episode",
                ),
                locus=Locus(episodes=[episodes[i].episode_id for i in offenders][:50]),
                blast=blast_over(len(offenders), ctx.profile.n_episodes),
                fix_machine={"action": "use_action_chunking", "target_family": family.value},
            )
        ]
