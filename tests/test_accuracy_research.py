"""Research-driven accuracy improvements (docs/07 §6, literature-backed hardening).

Two gaps a survey of the 2025–26 robot-learning-data literature surfaced, and the tests that
pin the fixes:

* **Sub-frame action↔observation misalignment.** Named the most common teleoperation data
  bug (arXiv 2605.26349 / the DQAF study): a 30–100 ms offset, visually imperceptible, that
  degrades fast tasks. Our integer-only lag search rounded it away; the sub-sample estimator
  now catches it.
* **Task imbalance.** Multitask policies learn rare tasks poorly when the data is skewed
  (*balanced behaviour cloning from imbalanced datasets*, Auton. Robots 2025) — a defect
  invisible in an aggregate profile.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

import _synth
from bohrin.detectors.base import AnalysisContext, Detector
from bohrin.detectors.coverage import TaskImbalanceDetector
from bohrin.detectors.temporal import ActionObservationLagDetector, _best_lag
from bohrin.ir.episode import Episode


def _fires(detector: Detector, ctx: AnalysisContext) -> bool:
    return len(list(detector.run(ctx))) > 0


# ------------------------------------------------------- sub-frame temporal misalignment


def test_best_lag_recovers_a_fractional_offset() -> None:
    """The sub-sample estimator resolves a half-step lag an integer search would miss."""
    t = np.linspace(0.0, 40.0, 400)
    cause = np.sin(t)
    # Shift the effect by a fractional 0.5 steps via interpolation, then first-difference it.
    shifted_state = np.interp(np.arange(len(t)) - 0.5, np.arange(len(t)), np.cumsum(cause))
    effect = np.diff(shifted_state)
    lag = _best_lag(cause, effect, max_lag=5)
    assert lag is not None
    assert 0.25 < abs(lag) < 0.9, f"expected a sub-step lag near 0.5, got {lag}"


def test_subframe_lag_is_below_the_old_one_step_threshold() -> None:
    """Guard the premise: this offset is < 1 step, so the old ``|lag| ≥ 1`` gate missed it.

    The new detector gates at 0.4 steps, so the same signal now trips it — that gap between
    the old and new thresholds is exactly the class of bug this improvement recovers.
    """
    t = np.linspace(0.0, 40.0, 400)
    cause = np.sin(t)
    shifted = np.interp(np.arange(len(t)) - 0.5, np.arange(len(t)), np.cumsum(cause))
    lag = _best_lag(cause, np.diff(shifted), max_lag=5)
    assert lag is not None
    assert 0.4 <= abs(lag) < 1.0  # caught by the new 0.4 gate, missed by the old 1.0 gate


def test_subframe_misalignment_fires_end_to_end() -> None:
    det = ActionObservationLagDetector()
    assert not _fires(det, _synth.build_context(_synth.clean_dataset(n_episodes=16)))

    episodes = _synth.clean_dataset(n_episodes=16)
    shifted = [_shift_state(ep, 0.5) for ep in episodes]
    assert _fires(det, _synth.build_context(shifted))


def _shift_state(ep: Episode, steps: float) -> Episode:
    """Delay proprio relative to action by a fractional number of steps (interpolated)."""
    proprio = np.asarray(ep.steps.proprio, dtype=np.float64)
    n = proprio.shape[0]
    idx = np.arange(n) - steps
    delayed = np.stack([np.interp(idx, np.arange(n), proprio[:, d]) for d in range(proprio.shape[1])], axis=1)
    return replace(ep, steps=replace(ep.steps, proprio=delayed))


# ----------------------------------------------------------------------- task imbalance


def test_balanced_tasks_do_not_fire() -> None:
    """A 50/50 two-task dataset is healthy — no imbalance finding."""
    ctx = _synth.build_context(_synth.labelled_dataset(n_episodes=16))
    assert not _fires(TaskImbalanceDetector(), ctx)


def test_unlabelled_dataset_is_silent() -> None:
    """No task labels → the check cannot and must not fire."""
    ctx = _synth.build_context(_synth.clean_dataset(n_episodes=16))
    assert not _fires(TaskImbalanceDetector(), ctx)


def test_single_task_is_never_imbalanced() -> None:
    episodes = [_synth.with_task(ep, "pick") for ep in _synth.clean_dataset(n_episodes=16)]
    assert not _fires(TaskImbalanceDetector(), _synth.build_context(episodes))


def test_starved_rare_task_is_caught() -> None:
    """15 episodes of one task, 1 of another → the rare task is starved."""
    common = [_synth.with_task(ep, "open the drawer") for ep in _synth.clean_dataset(n_episodes=15)]
    rare = [_synth.with_task(_synth.clean_dataset(n_episodes=1, seed=99)[0], "fold the towel")]
    findings = list(TaskImbalanceDetector().run(_synth.build_context(common + rare)))
    assert findings
    metrics = findings[0].evidence.metrics
    assert metrics["rarest_count"] == 1.0
    assert metrics["starvation_ratio"] >= 4.0
    assert findings[0].fix.machine["rarest"] == "fold the towel"


def test_imbalance_is_in_the_registry_and_scoped_to_coverage() -> None:
    from bohrin.detectors.registry import discover

    match = [d for d in discover() if d.id == "coverage.task_imbalance"]
    assert len(match) == 1
    assert match[0].family.value == "COVERAGE"
