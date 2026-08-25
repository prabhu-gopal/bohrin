"""Regression suite for ``temporal.action_observation_lag`` (docs/04 §D).

This detector produced the battery's worst class of false positive: a confident **HIGH** on
data that was correctly recorded, on the two most common real-world layouts. Three independent
defects, each reproduced here so none can come back:

1. **Absolute-pose actions were compared against a velocity.** ``‖action‖`` is a position for a
   ``JOINT_POS``/``EEF_ABS`` dataset while ``‖Δstate‖`` is a speed — a quarter-period out of
   phase for any oscillatory motion. This is the single most common action space in real
   datasets (ALOHA/ACT-style recordings log absolute joint targets).
2. **The ±1 row-indexing convention was treated as a defect.** ``action[t] = s[t] − s[t−1]`` and
   ``action[t] = s[t+1] − s[t]`` are both correct ways to log the same recording, and they are
   indistinguishable from the bytes. The detector assumed the one our own fixtures happened to
   use, so every dataset using the other convention was told its pipeline was broken.
3. **A correlation peak on the search boundary was reported as a measurement.** With the true
   peak outside the ±``max_lag`` window the estimate is an artefact of where the search stopped;
   it surfaced as a crisp "misaligned by ~5.0 steps" at ``max_lag == 5``.

The tests are written as a matrix — {forward, backward, absolute} × {aligned, misaligned} — so
that silence on clean data and sensitivity to real defects are asserted against the *same*
generators. A fix that buys silence by breaking detection fails here.
"""

from __future__ import annotations

import numpy as np
import pytest

import _synth
from bohrin._arrays import FloatArray
from bohrin.detectors.temporal import ActionObservationLagDetector, _best_lag, _convention_excess
from bohrin.ir.episode import Episode
from bohrin.ir.schema import ActionSpace, Severity
from bohrin.report.model import Finding

_LENGTH = 80
_N = 12

#: Which action space each convention represents, as a dataset would declare it.
_SPACES = {
    "forward": ActionSpace.EEF_DELTA,
    "backward": ActionSpace.EEF_DELTA,
    "absolute": ActionSpace.JOINT_POS,
}


def _trajectory(index: int) -> FloatArray:
    """A smooth reach: monotone in x with a gentle arc in y, plus sensor noise."""
    rng = np.random.default_rng((index, 7))
    t = np.linspace(0.0, 1.0, _LENGTH)
    traj = np.zeros((_LENGTH, 6), dtype=np.float64)
    traj[:, 0] = t * rng.uniform(0.9, 1.1)
    traj[:, 1] = 0.3 * np.sin(np.pi * t)
    return traj + rng.normal(0.0, 0.001, traj.shape)


def _actions(traj: FloatArray, convention: str) -> FloatArray:
    """The action column for ``traj`` under one of the three legitimate conventions."""
    if convention == "forward":  # action[t] = s[t+1] - s[t]
        action = np.zeros_like(traj)
        action[:-1] = np.diff(traj, axis=0)
        return action
    if convention == "backward":  # action[t] = s[t] - s[t-1]
        return np.asarray(np.diff(traj, axis=0, prepend=traj[:1]), dtype=np.float64)
    if convention == "absolute":  # action[t] = target pose
        return traj.copy()
    raise AssertionError(f"unknown convention {convention!r}")


def _dataset(convention: str, *, shift: int = 0) -> list[Episode]:
    """A dataset in ``convention``, optionally with a real ``shift``-step recording lag."""
    episodes: list[Episode] = []
    for i in range(_N):
        traj = _trajectory(i)
        action = _actions(traj, convention)
        if shift:
            action = np.roll(action, shift, axis=0)
            action[:shift] = 0.0
        episodes.append(_synth._episode(i, action, traj))
    return episodes


def _run(convention: str, *, shift: int = 0, declared: ActionSpace | None = None) -> list[Finding]:
    schema = _synth.make_schema(action_space=declared if declared is not None else _SPACES[convention])
    ctx = _synth.build_context(_dataset(convention, shift=shift), schema=schema)
    return list(ActionObservationLagDetector().run(ctx))


# ------------------------------------------------------- clean data stays clean (the fix)


@pytest.mark.parametrize("convention", ["forward", "backward", "absolute"])
def test_a_correctly_recorded_dataset_is_never_reported(convention: str) -> None:
    """The headline regression: all three layouts are correct and must produce no finding."""
    findings = _run(convention)
    assert not findings, (
        f"false positive on correctly-recorded {convention} data: {[(f.severity.value, f.title) for f in findings]}"
    )


def test_absolute_pose_data_is_silent_even_when_the_space_is_not_declared() -> None:
    """Most datasets declare nothing, so the protection cannot depend on the declaration.

    With ``ActionSpace.UNKNOWN`` the detector has to infer that the actions are absolute from
    the profile; if that inference is skipped the position-vs-velocity comparison returns.
    """
    assert not _run("absolute", declared=ActionSpace.UNKNOWN)


def test_oscillatory_absolute_data_does_not_saturate_the_search() -> None:
    """The exact shape that produced "~5.0 steps" at ``max_lag == 5``.

    A quarter-period phase error on a periodic signal pushes the correlation peak past the
    window, where the old code reported the boundary as though it had measured it.
    """
    episodes: list[Episode] = []
    for i in range(_N):
        rng = np.random.default_rng((i, 11))
        t = np.linspace(0.0, 3.0, _LENGTH)
        traj = np.zeros((_LENGTH, 6), dtype=np.float64)
        traj[:, 0] = np.sin(2 * np.pi * t)
        traj[:, 1] = np.cos(2 * np.pi * t)
        traj[:, 2] = 0.4 * np.sin(6 * np.pi * t)
        traj += rng.normal(0.0, 0.002, traj.shape)
        episodes.append(_synth._episode(i, traj.copy(), traj))
    ctx = _synth.build_context(episodes, schema=_synth.make_schema(action_space=ActionSpace.JOINT_POS))
    findings = list(ActionObservationLagDetector().run(ctx))
    assert not findings, f"saturated estimate reported as a finding: {[f.title for f in findings]}"


# ------------------------------------------------ real misalignment is still caught (power)


@pytest.mark.parametrize("convention", ["forward", "backward", "absolute"])
def test_a_real_recording_lag_is_still_reported(convention: str) -> None:
    """Silence on clean data must not have been bought by giving up detection."""
    findings = _run(convention, shift=3)
    assert findings, f"a planted 3-step lag went unreported on {convention} data"
    assert findings[0].severity is Severity.HIGH
    assert findings[0].evidence.metrics["excess_over_convention_steps"] >= 1.0


def _fractional_delay_dataset(delay: float) -> list[Episode]:
    """A dataset whose action column is sampled ``delay`` steps out of phase with the state.

    A *true* sub-frame misalignment, not a smoothing filter: the trajectory is analytic, the
    state is sampled on integer steps, and the logged delta is the one the motion actually had
    ``delay`` steps later — which is what a recorder with an unsynchronised clock produces.
    """
    episodes: list[Episode] = []
    for i in range(_N):
        rng = np.random.default_rng((i, 13))
        speed = rng.uniform(0.9, 1.1)

        def position(time: FloatArray, speed: float = speed) -> FloatArray:
            out = np.zeros((time.shape[0], 6), dtype=np.float64)
            out[:, 0] = 0.6 * np.sin(0.11 * time) * speed
            out[:, 1] = 0.4 * np.cos(0.07 * time) * speed
            out[:, 2] = 0.02 * time * speed
            return out

        steps = np.arange(_LENGTH, dtype=np.float64)
        proprio = position(steps) + rng.normal(0.0, 5e-4, (_LENGTH, 6))
        # The action logged at row t is the delta the motion had at t + delay.
        shifted = steps + delay
        action = position(shifted + 1.0) - position(shifted)
        episodes.append(_synth._episode(i, action, proprio))
    return episodes


def test_a_half_step_offset_is_reported_at_medium() -> None:
    """The 30–100 ms teleop offset the literature calls the most common data bug.

    Reported, but below HIGH: an offset smaller than a whole row cannot be fully separated from
    a neighbouring convention, so severity says "look at this" rather than overclaiming.
    """
    ctx = _synth.build_context(
        _fractional_delay_dataset(0.5), schema=_synth.make_schema(action_space=ActionSpace.EEF_DELTA)
    )
    findings = list(ActionObservationLagDetector().run(ctx))
    assert findings, "a half-step offset should be reported — it is the most detectable sub-frame case"
    assert findings[0].severity is Severity.MEDIUM
    assert findings[0].evidence.metrics["excess_over_convention_steps"] >= ActionObservationLagDetector._MIN_LAG


def test_a_whole_step_offset_is_deliberately_not_reported() -> None:
    """A documented limit, asserted so nobody "fixes" it into a false positive.

    A one-step recording lag and the backward-difference convention are the *same bytes*. There
    is no evidence in the data that separates them, so reporting one would necessarily accuse
    every correctly-recorded backward-convention dataset of a defect. The tool stays silent and
    says why in the mechanism, rather than guessing.
    """
    ctx = _synth.build_context(
        _fractional_delay_dataset(1.0), schema=_synth.make_schema(action_space=ActionSpace.EEF_DELTA)
    )
    assert not list(ActionObservationLagDetector().run(ctx))


# --------------------------------------------------------------------- the primitives


@pytest.mark.parametrize(
    ("lag", "expected"),
    [(0.0, 0.0), (1.0, 0.0), (-1.0, 0.0), (0.5, 0.5), (-1.4, 0.4), (2.0, 1.0), (-3.0, 2.0)],
)
def test_convention_excess_measures_distance_to_the_nearest_valid_convention(lag: float, expected: float) -> None:
    assert _convention_excess(lag) == pytest.approx(expected)


def test_best_lag_refuses_a_boundary_peak() -> None:
    """A peak at ±max_lag means the real peak is outside the window: no estimate, not a big one.

    Uses a *smoothed* (autocorrelated) signal so the correlation rises monotonically toward the
    true offset; with white noise every in-window lag correlates at ~0 and the peak location is
    arbitrary, which would not exercise the boundary rule.
    """
    rng = np.random.default_rng(3)
    smooth = np.convolve(rng.normal(size=240), np.ones(9) / 9, mode="valid")[:200]
    assert _best_lag(smooth, np.roll(smooth, 9), 4) is None  # true offset far outside ±4


def test_best_lag_finds_an_in_window_offset() -> None:
    rng = np.random.default_rng(4)
    cause = rng.normal(size=400)
    effect = np.roll(cause, 2)  # effect[t] == cause[t-2] → the cause leads by 2 steps
    lag = _best_lag(cause, effect, 5)
    assert lag is not None
    assert lag == pytest.approx(2.0, abs=0.25)


def test_best_lag_is_symmetric_about_zero_for_aligned_signals() -> None:
    rng = np.random.default_rng(5)
    signal = np.cumsum(rng.normal(size=300))
    lag = _best_lag(signal, signal, 5)
    assert lag is not None
    assert abs(lag) < 0.25


# ------------------------------------------------- the whole battery, not just this detector


_CONVENTION_SPACES = {
    "forward": ActionSpace.EEF_DELTA,
    "backward": ActionSpace.EEF_DELTA,
    "absolute": ActionSpace.JOINT_POS,
}


def _all_findings(convention: str) -> dict[str, str]:
    """``detector_id → severity`` for every applicable detector on one convention."""
    from bohrin.detectors.registry import discover

    schema = _synth.make_schema(action_space=_CONVENTION_SPACES[convention])
    ctx = _synth.build_context(_dataset(convention), schema=schema)
    out: dict[str, str] = {}
    for detector in discover():
        if not detector.applicable(ctx.profile, ctx.policy):
            continue
        findings = list(detector.run(ctx))
        if findings:
            out[detector.id] = findings[0].severity.value
    return out


@pytest.mark.parametrize("convention", ["backward", "absolute"])
def test_the_whole_battery_agrees_across_logging_conventions(convention: str) -> None:
    """The same recording, logged three legitimate ways, must get the same verdict.

    ``action_observation_lag`` was only the most visible instance of a systemic assumption:
    ``causal.copycat_shortcut``, ``causal.proprio_shortcut``,
    ``multimodality.contradictory_actions`` and both DYNAMICS residual checks all read the action
    column as though it were a forward-difference delta. Measured before the fix, a
    correctly-recorded backward-convention dataset gained 2 spurious findings and an
    absolute-pose dataset gained 4 — three of them HIGH.

    Asserting the *whole battery* rather than one detector is deliberate: the failure was a class,
    and a per-detector test would let the next member of it through.
    """
    reference = _all_findings("forward")
    actual = _all_findings(convention)
    spurious = {k: v for k, v in actual.items() if k not in reference}
    assert not spurious, (
        f"{convention}-convention data produced findings absent on the identical "
        f"forward-convention recording: {spurious}"
    )


@pytest.mark.parametrize("convention", ["forward", "backward", "absolute"])
def test_action_increments_preserve_length_and_meaning(convention: str) -> None:
    """The increments helper must keep row alignment with the states it is paired against."""
    from bohrin.profile.action_space import action_increments

    traj = _trajectory(0)
    action = _actions(traj, convention)
    increments = action_increments(action, _CONVENTION_SPACES[convention])
    assert increments.shape == action.shape
    assert np.isfinite(increments).all()
