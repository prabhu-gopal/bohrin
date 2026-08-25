"""Family D — IDLE / TEMPORAL: is time well used? (docs/04 §D).

``temporal.idle_frames`` uses DROID's published QC rule — keep only contiguous non-idle
action segments of ≥ 1 second (docs/07 §7). ``temporal.action_observation_lag`` estimates
a systematic delay between logged actions and the state change they cause.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from bohrin._arrays import BoolArray, FloatArray
from bohrin.detectors._common import (
    blast_over,
    channel,
    dataset_provenance,
    make_finding,
    sparkline,
)
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.ir.schema import Family, Severity
from bohrin.profile.action_space import is_absolute, resolve_action_space
from bohrin.report.model import Evidence, Finding, Locus

_ACTION_EPS = 1e-3  # ‖action‖ below this is "no command"
_STATE_EPS = 1e-3  # ‖Δstate‖ below this is "not moving"


class IdleFramesDetector(Detector):
    """Reports idle fraction and flags heavy idle padding using the DROID ≥ 1 s rule."""

    id = "temporal.idle_frames"
    family = Family.TEMPORAL
    requires = Requirements(needs_proprio=True)
    description = "Detects idle frames (no command, no motion) that bias the policy toward inaction."

    _DATASET_FRAC = 0.15  # > 15% idle across the dataset is worth flagging

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        hz = ctx.profile.control_hz or 1.0
        min_run = max(1, round(hz))  # 1 second of contiguous frames
        total_idle = 0
        total_steps = 0
        offenders: list[str] = []
        for ep in ctx.episodes:
            action = np.asarray(ep.steps.action, dtype=np.float64)
            proprio = channel(ep, prefer_proprio=True)
            idle = _idle_mask(action, proprio)
            total_idle += int(idle.sum())
            total_steps += idle.shape[0]
            if _longest_true_run(idle) >= min_run and idle.mean() > 0.3:
                offenders.append(ep.episode_id)
        if total_steps == 0:
            return []
        idle_frac = total_idle / total_steps
        if idle_frac < self._DATASET_FRAC and not offenders:
            return []
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=1.0,
                title=f"{idle_frac * 100:.0f}% of all frames are idle",
                mechanism=(
                    "Long idle spans bias the policy toward inaction ('do nothing' becomes "
                    "the modal action) and waste action-chunk capacity."
                ),
                fix_text=(
                    "Trim idle lead-in/lead-out; keep only contiguous non-idle segments of ≥ 1 second (the DROID rule)."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={"idle_fraction": idle_frac, "n_heavy_episodes": float(len(offenders))},
                    thresholds={
                        "dataset_frac": self._DATASET_FRAC,
                        "min_run_frames": float(min_run),
                    },
                ),
                locus=Locus(episodes=offenders[:50]),
                blast=blast_over(len(offenders), ctx.profile.n_episodes, frac_steps=idle_frac),
                fix_machine={"action": "trim_idle", "min_run_frames": min_run},
            )
        ]


#: Row-indexing conventions that are all *correct* ways to log the same recording, and
#: therefore all indistinguishable from the bytes alone:
#:
#: * ``0``  — ``action[t] == state[t+1] − state[t]``: the action is logged against the state it
#:   was issued *from* (the convention ``_synth.integrate`` documents).
#: * ``-1`` — ``action[t] == state[t] − state[t−1]``: the action is logged against the state it
#:   *produced*. Equally common in the wild.
#: * ``+1`` — one further row of buffering, as appears when a target-pose command is logged
#:   ahead of the state that achieves it.
#:
#: A dataset choosing any of these is not defective, so the detector reports only the *excess*
#: over the nearest one. Ignoring this is what made a correctly-recorded backward-difference
#: dataset report a HIGH "your pipeline is misaligned", on the reasoning that the offset must
#: be a bug because our own fixtures used the other convention.
_CONVENTION_LAGS: tuple[float, ...] = (-1.0, 0.0, 1.0)


def _convention_excess(lag: float) -> float:
    """How far ``lag`` is from the nearest legitimate row-indexing convention, in steps."""
    return min(abs(lag - candidate) for candidate in _CONVENTION_LAGS)


#: Wall-clock window in which a *positive* lag is attributable to controller tracking rather
#: than to a recording fault, for absolute (position-target) action spaces.
#:
#: When the action is a pose or joint **target**, the follower does not arrive instantly: a
#: position/PD controller needs several control steps to close the gap, so the state change
#: genuinely trails the command. That delay is physics, not misalignment, and it is present in
#: correct data. Measured on three independent position-controlled datasets:
#:
#: * ``lerobot/pusht``                        10 Hz  → +2.04 steps (204 ms)
#: * ``lerobot/svla_so101_pickplace``         30 Hz  → +3.59 steps (120 ms)
#: * ``lerobot/aloha_sim_transfer_cube_human`` 50 Hz  → +3.87 steps ( 77 ms)
#:
#: The last one is decisive: it is a **simulator**, so it has no sensor latency, no clock skew
#: and no network delay. Its 77 ms can only be controller response, which proves a multi-step
#: positive lag is expected in correct absolute-space data. Before this allowance existed all
#: three reported a HIGH "re-align your timestamps" — advice that would have corrupted data
#: that was never misaligned. 0.25 s keeps headroom over the slowest observed response.
_SETTLING_SECONDS = 0.25
#: Fallback when the control rate is undeclared: the mid-range of the settling values above.
_DEFAULT_SETTLING_STEPS = 2.5


def _settling_allowance(*, absolute: bool, hz: float | None) -> float:
    """Extra positive lag, in steps, that controller tracking alone can explain."""
    if not absolute:
        return 0.0
    return _SETTLING_SECONDS * hz if hz else _DEFAULT_SETTLING_STEPS


def _reportable_excess(lag: float, allowance: float) -> float:
    """Lag beyond every benign explanation: row-indexing convention *and* controller settling.

    The allowance only widens the band in the **positive** direction. A negative lag means the
    state moved before the action that supposedly caused it, which no controller can produce, so
    it stays measured against the row-indexing conventions alone.
    """
    top = max(_CONVENTION_LAGS)
    if lag > top and allowance > 0.0:
        return max(0.0, lag - (top + allowance))
    return _convention_excess(lag)


class ActionObservationLagDetector(Detector):
    """Estimates a systematic lag between logged actions and the state change they cause.

    **What this compares, and why it depends on the action space.** The premise is that a
    logged action should explain the state change around it. That holds when the action *is* an
    increment (a delta or a velocity). When the action is an **absolute pose or joint target**,
    ``‖action‖`` is a position and ``‖Δstate‖`` is a speed — different physical quantities, a
    quarter-period out of phase for any oscillatory motion. Correlating them produces a large,
    confident, meaningless lag: measured on clean absolute-pose data it pinned at the search
    boundary and reported "misaligned by ~5 steps". So for absolute action spaces the action is
    differenced first, putting both signals in the same units before any comparison.

    ``JOINT_POS`` is among the most common action spaces in real datasets (it is what
    ALOHA/ACT-style recordings log), which made this the highest-traffic false positive in the
    battery — precisely the trust-destroying failure the docs warn about.
    """

    id = "temporal.action_observation_lag"
    family = Family.TEMPORAL
    requires = Requirements(needs_proprio=True, min_episodes=4)
    description = "Detects observation/action misalignment — a wrong phase relationship the policy will learn."

    _MAX_LAG = 5

    #: Excess over the nearest convention, in steps, worth reporting.
    #:
    #: Because the legitimate conventions sit one step apart, the excess **cannot exceed 0.5**
    #: for a sub-step offset: a half-step delay is equidistant from two valid readings and is
    #: therefore the *most* detectable sub-frame case, while an offset approaching a whole step
    #: is indistinguishable from the neighbouring convention and is invisible by construction.
    #: That is a property of the ambiguity, not of this implementation, and it is why a 1-step
    #: recording lag is not reportable — it *is* the backward-difference convention.
    #:
    #: Measured on every clean fixture in the suite the excess sits at ≤ 0.025 steps, so this
    #: threshold keeps ~8× headroom over the observed noise floor while still covering the
    #: middle of the sub-frame band.
    _MIN_LAG = 0.2
    #: Excess at or above this is a genuine misalignment no row-indexing choice explains.
    _HIGH_LAG = 1.0

    def _episode_lags(self, ctx: AnalysisContext) -> tuple[list[float], bool]:
        """Per-episode lag estimates, and whether the action had to be differenced."""
        absolute = is_absolute(resolve_action_space(ctx.profile, ctx.schema.action_space))
        lags: list[float] = []
        for ep in ctx.episodes:
            action = np.asarray(ep.steps.action, dtype=np.float64)
            proprio = channel(ep, prefer_proprio=True)
            if action.shape[0] < 3 * self._MAX_LAG or proprio.shape[0] != action.shape[0]:
                continue
            # Absolute targets are positions; difference them so both series are increments.
            cause = np.diff(action, axis=0) if absolute else action[:-1]
            effect = np.diff(proprio, axis=0)
            lag = _best_lag(
                np.linalg.norm(cause, axis=1),
                np.linalg.norm(effect, axis=1),
                self._MAX_LAG,
            )
            if lag is not None:
                lags.append(lag)
        return lags, absolute

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        best_lags, differenced = self._episode_lags(ctx)
        if len(best_lags) < 4:
            return []
        hz = ctx.profile.control_hz
        allowance = _settling_allowance(absolute=differenced, hz=hz)
        median_lag = float(np.median(best_lags))
        excess = _reportable_excess(median_lag, allowance)
        # Report the excess beyond *every* benign explanation, not the raw lag.
        if excess < self._MIN_LAG:
            return []
        # And require the offset to be consistent across episodes: a real pipeline offset
        # affects every recording, one noisy trajectory does not.
        agree = float(np.mean([_reportable_excess(lag, allowance) >= self._MIN_LAG for lag in best_lags]))
        if agree < 0.6:
            return []
        # An effect preceding its cause is unambiguous; a positive lag on position targets is
        # confounded with controller response, so it is reported more cautiously and named as
        # such. Getting this wrong in the *recommendation* is what makes a false positive
        # expensive: "re-align your timestamps" applied to correct data corrupts it.
        acausal = median_lag < min(_CONVENTION_LAGS)
        ms = f" (~{excess / hz * 1000:.0f} ms)" if hz else ""
        if acausal:
            severity = Severity.HIGH if excess >= self._HIGH_LAG else Severity.MEDIUM
            title = f"State changes ~{excess:.1f} step(s){ms} *before* the action that caused it"
            fix_text = (
                "The action and observation streams are ordered wrongly — no controller responds "
                "before it is commanded. Check the recording pipeline's synchronization and "
                "re-align the timestamps."
            )
        elif differenced:
            # Confounded direction: cap at MEDIUM whatever the magnitude.
            severity = Severity.MEDIUM
            title = f"State trails the commanded target by ~{excess:.1f} step(s){ms} more than tracking explains"
            fix_text = (
                "On an absolute (position-target) action space some lag is normal controller "
                "response, so confirm before changing anything: compare the commanded and achieved "
                "positions on one episode. If the controller is tracking well, the residual points "
                "at recording synchronization instead."
            )
        else:
            severity = Severity.HIGH if excess >= self._HIGH_LAG else Severity.MEDIUM
            title = f"Actions and state change are misaligned by ~{excess:.1f} step(s){ms}"
            fix_text = "Check the recording pipeline's action/observation synchronization and re-align timestamps."
        return [
            make_finding(
                self,
                severity=severity,
                confidence=min(1.0, agree),
                title=title,
                mechanism=(
                    "A systematic delay between an observation and the logged action teaches "
                    "the policy a wrong phase relationship — subtle and very damaging at rollout. "
                    "Even a sub-frame offset is visually imperceptible in the logs yet degrades "
                    "fast tasks. This is measured as the offset *beyond* the nearest whole-row "
                    "logging convention, so a dataset that simply indexes its action column "
                    "against the previous state is not reported — and, for absolute action "
                    "spaces, also beyond the delay a position controller needs to reach its "
                    "target, which is present in correct data."
                ),
                fix_text=fix_text,
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "median_lag_steps": median_lag,
                        "excess_over_convention_steps": excess,
                        "settling_allowance_steps": allowance,
                        "agreement": agree,
                    },
                    thresholds={"min_excess_steps": self._MIN_LAG, "high_excess_steps": self._HIGH_LAG},
                    notes=(
                        "action differenced first (absolute action space); positive lag additionally "
                        f"allowed {allowance:.1f} step(s) for controller settling"
                        if differenced
                        else "action used directly (delta action space)"
                    ),
                    series=sparkline(np.asarray(sorted(best_lags), dtype=np.float64)),
                    series_label="per-episode estimated lag (steps)",
                ),
                blast=blast_over(len(best_lags), ctx.profile.n_episodes),
            )
        ]


def _idle_mask(action: FloatArray, proprio: FloatArray) -> BoolArray:
    """True where there is neither a command nor motion."""
    no_command = np.linalg.norm(action, axis=1) < _ACTION_EPS
    if proprio.shape[0] == action.shape[0] and proprio.shape[0] >= 2:
        delta = np.zeros(proprio.shape[0], dtype=np.float64)
        delta[1:] = np.linalg.norm(np.diff(proprio, axis=0), axis=1)
        no_motion = delta < _STATE_EPS
    else:
        no_motion = np.ones(action.shape[0], dtype=bool)
    return no_command & no_motion


def _longest_true_run(mask: BoolArray) -> int:
    best = run = 0
    for v in mask:
        run = run + 1 if v else 0
        best = max(best, run)
    return best


def _best_lag(cause: FloatArray, effect: FloatArray, max_lag: int) -> float | None:
    """Sub-sample lag maximizing cross-correlation of ``cause`` with ``effect``.

    Returns a **fractional** lag in steps. The literature's most common teleoperation bug is
    a 30–100 ms action↔observation misalignment that is "visually imperceptible" yet degrades
    fast-task policies (arXiv 2605.26349 and the DQAF study); at 20–30 Hz that is often a
    *sub-frame* offset an integer-only search rounds away to zero. So after locating the
    best integer lag we fit a parabola to its neighbouring correlations and return the
    interpolated peak — the standard sub-sample time-delay estimator.

    ``effect`` is one shorter than ``cause`` (it is a first difference), so we align on the
    overlap. Returns ``None`` if either signal is degenerate, **or if the peak sits on the
    search boundary** — there the true maximum lies outside the window, so the reported value
    is an artefact of where we stopped looking rather than a measurement. Clean absolute-pose
    data hit exactly this case and yielded a confident "misaligned by 5.0 steps" at
    ``max_lag == 5``; a saturated estimate is not a small error, it is no estimate at all.
    """
    c = cause[: effect.shape[0]]
    e = effect[: cause.shape[0]]
    # Corrupt samples would make the mean/std — and therefore every correlation — NaN.
    finite = np.isfinite(c) & np.isfinite(e)
    if not bool(finite.all()):
        c, e = c[finite], e[finite]
    if c.shape[0] < 3 * max_lag:
        return None
    if c.std() < _ACTION_EPS or e.std() < _STATE_EPS:
        return None
    c = (c - c.mean()) / c.std()
    e = (e - e.mean()) / e.std()
    n = c.shape[0]
    corr_at: dict[int, float] = {}
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            a, b = c[: n - lag], e[lag:]
        else:
            a, b = c[-lag:], e[: n + lag]
        if a.shape[0] < max_lag:
            continue
        corr_at[lag] = float(np.mean(a * b))
    if not corr_at:
        return None
    best_lag = max(corr_at, key=lambda k: corr_at[k])
    if abs(best_lag) >= max_lag:
        return None  # peak on (or beyond) the boundary: unmeasurable, not "a large lag"
    return best_lag + _parabolic_offset(corr_at, best_lag)


def _parabolic_offset(corr_at: dict[int, float], peak: int) -> float:
    """Sub-sample correction to a correlation peak via 3-point parabolic interpolation.

    With the peak value ``y0`` and its neighbours ``y-``/``y+``, the vertex offset is
    ``0.5·(y- − y+) / (y- − 2·y0 + y+)``, clamped to ``±0.5`` so it never leaves the cell.
    Returns 0 at the search boundary, where only one neighbour exists.
    """
    left, right = corr_at.get(peak - 1), corr_at.get(peak + 1)
    if left is None or right is None:
        return 0.0
    y0 = corr_at[peak]
    denom = left - 2.0 * y0 + right
    if abs(denom) < 1e-12:
        return 0.0
    return float(np.clip(0.5 * (left - right) / denom, -0.5, 0.5))
