"""Fault-injection fixtures for the Phase 3 detectors (docs/06 P3, docs/07 §8).

Same contract as the P1/P2 fault suites: clean data must produce **no** finding, and data
with the matching defect injected must produce at least one. The final test re-asserts the
zero-false-HIGH bar across the *whole* registry, which is what caught the path-efficiency
division artifact while this module was being written.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

import _synth
from bohrin.detectors.base import AnalysisContext, Detector
from bohrin.detectors.integrity import SplitLeakageDetector
from bohrin.detectors.kinematics import (
    CurvatureDetector,
    GripperChatterDetector,
    NonMarkovianPauseDetector,
    PathEfficiencyDetector,
)
from bohrin.detectors.scale import (
    ConstantOrDegenerateChannelDetector,
    UnitScaleInconsistencyDetector,
)
from bohrin.ir.episode import Episode


def _fires(detector: Detector, ctx: AnalysisContext) -> bool:
    return len(list(detector.run(ctx))) > 0


def _clean_ctx(n: int = 16) -> AnalysisContext:
    return _synth.build_context(_synth.clean_dataset(n_episodes=n))


# ------------------------------------------------------------------------------ STATS


def test_constant_or_degenerate_channel() -> None:
    det = ConstantOrDegenerateChannelDetector()
    assert not _fires(det, _clean_ctx())

    episodes = _synth.clean_dataset(n_episodes=16)
    patched = []
    for ep in episodes:
        action = np.array(ep.steps.action, copy=True)
        # Not zero — a *near*-constant channel, which stats.dead_dimension deliberately
        # ignores. This is the seam between the two detectors.
        action[:, 1] = 1e-5 * np.arange(action.shape[0])
        patched.append(replace(ep, steps=replace(ep.steps, action=action)))
    assert _fires(det, _synth.build_context(patched))


def test_dead_and_degenerate_do_not_double_report() -> None:
    """An exactly-constant channel belongs to dead_dimension alone."""
    episodes = _synth.inject_dead_dimension(_synth.clean_dataset(n_episodes=16), dim=1)
    assert not _fires(ConstantOrDegenerateChannelDetector(), _synth.build_context(episodes))


def test_unit_scale_inconsistency() -> None:
    det = UnitScaleInconsistencyDetector()
    assert not _fires(det, _clean_ctx())

    episodes = _synth.clean_dataset(n_episodes=16)
    patched = []
    for ep in episodes:
        action = np.array(ep.steps.action, copy=True)
        # Channel 0 recorded in degrees (±180) while the rest are radians (±π).
        action[:, 0] = 180.0 * np.sin(np.arange(action.shape[0]) / 5.0)
        patched.append(replace(ep, steps=replace(ep.steps, action=action)))
    findings = list(det.run(_synth.build_context(patched)))
    assert findings
    assert "radians" in findings[0].mechanism


# ------------------------------------------------------------------------- SMOOTHNESS


def test_path_efficiency() -> None:
    det = PathEfficiencyDetector()
    assert not _fires(det, _clean_ctx())

    episodes = _synth.clean_dataset(n_episodes=16)
    patched = list(episodes)
    for i in (3, 9):
        patched[i] = _wandering(episodes[i])
    assert _fires(det, _synth.build_context(patched))


def test_path_efficiency_ignores_episodes_that_return_to_start() -> None:
    """The ratio divides by net displacement; a loop must not be called 'wandering'."""
    episodes = _synth.clean_dataset(n_episodes=16)
    patched = []
    for ep in episodes:
        proprio = np.array(ep.steps.proprio, copy=True)
        proprio[-1] = proprio[0]  # ends exactly where it began
        patched.append(replace(ep, steps=replace(ep.steps, proprio=proprio)))
    assert not _fires(PathEfficiencyDetector(), _synth.build_context(patched))


def test_curvature() -> None:
    """Measured on *smooth* demos, which is what real teleoperation produces.

    On the random-walk `clean_dataset` fixture curvature is saturated (every trajectory
    turns constantly), so an erratic episode cannot stand out — the metric needs a
    realistic baseline to be falsifiable at all. See `_synth.smooth_dataset`.
    """
    det = CurvatureDetector()
    assert not _fires(det, _synth.build_context(_synth.smooth_dataset(n_episodes=16)))
    assert not _fires(det, _clean_ctx())

    planted = _synth.smooth_dataset(n_episodes=16, erratic_at=(2, 5))
    assert _fires(det, _synth.build_context(planted))


# --------------------------------------------------------------------------- TEMPORAL


def test_gripper_chatter() -> None:
    det = GripperChatterDetector()
    clean = _binary_gripper_dataset(chatter_in=())
    assert not _fires(det, _synth.build_context(clean))

    noisy = _binary_gripper_dataset(chatter_in=(1, 4, 7))
    assert _fires(det, _synth.build_context(noisy))


def test_non_markovian_pause() -> None:
    det = NonMarkovianPauseDetector()
    assert not _fires(det, _clean_ctx())

    episodes = _synth.clean_dataset(n_episodes=16)
    patched = [_pause_then_act(ep) for ep in episodes]
    assert _fires(det, _synth.build_context(patched))


def test_pause_severity_depends_on_the_target_policy() -> None:
    """The same data is fatal for BC and a non-issue for ACT — severity must reflect that."""
    from bohrin.ir.schema import PolicyFamily, PolicyProfile, Severity

    episodes = [_pause_then_act(ep) for ep in _synth.clean_dataset(n_episodes=16)]
    base = _synth.build_context(episodes)

    bc = list(NonMarkovianPauseDetector().run(replace(base, policy=PolicyProfile(family=PolicyFamily.BC_MLP))))
    act = list(NonMarkovianPauseDetector().run(replace(base, policy=PolicyProfile(family=PolicyFamily.ACT))))
    assert bc and act
    assert bc[0].severity is Severity.HIGH
    assert act[0].severity is Severity.LOW


# -------------------------------------------------------------------------- INTEGRITY


def test_split_leakage() -> None:
    det = SplitLeakageDetector()
    # Distinct episodes, honestly split → silent.
    episodes = _synth.clean_dataset(n_episodes=16)
    honest = [replace(ep, split="train" if i < 12 else "val") for i, ep in enumerate(episodes)]
    assert not _fires(det, _synth.build_context(honest))

    # The last four val episodes are near-copies of train episodes.
    leaked = list(honest)
    for i in range(12, 16):
        source = honest[i - 12]
        leaked[i] = replace(
            source,
            episode_id=f"leaked_{i}",
            split="val",
            steps=replace(source.steps, action=np.array(source.steps.action, copy=True)),
        )
    findings = list(det.run(_synth.build_context(leaked)))
    assert findings
    assert "recording session" in findings[0].fix.text


def test_split_leakage_is_silent_without_declared_splits() -> None:
    """Most formats declare no split; inventing one would be worse than not checking."""
    assert not _fires(SplitLeakageDetector(), _clean_ctx())


# ------------------------------------------------------------- the zero-false-HIGH bar


def test_clean_data_produces_no_findings_from_any_detector() -> None:
    """Re-run across the *whole* registry, now 47 detectors deep."""
    from bohrin.detectors.registry import discover

    ctx = _clean_ctx()
    for det in discover():
        if not det.applicable(ctx.profile, ctx.policy):
            continue
        assert not _fires(det, ctx), f"{det.id} fired on clean data"


# ------------------------------------------------------------------------------ utils


def _wandering(ep: Episode) -> Episode:
    """A trajectory that reaches the same endpoint via a long detour."""
    proprio = np.array(ep.steps.proprio, copy=True)
    t = np.linspace(0.0, 6.0 * np.pi, proprio.shape[0])
    detour = np.zeros_like(proprio)
    detour[:, 0] = 3.0 * np.sin(t)
    detour[:, 1] = 3.0 * np.cos(t) - 3.0
    detour[-1] = 0.0  # keep the endpoint, so only the *path* changed
    return replace(ep, steps=replace(ep.steps, proprio=proprio + detour))


def _pause_then_act(ep: Episode) -> Episode:
    """Freeze the state for a stretch while the action changes — the pause signature."""
    proprio = np.array(ep.steps.proprio, copy=True)
    action = np.array(ep.steps.action, copy=True)
    lo, hi = 10, 24
    proprio[lo:hi] = proprio[lo]  # the state does not move
    action[lo : (lo + hi) // 2] = 0.0  # ... but the command changes partway through
    action[(lo + hi) // 2 : hi] = 5.0
    return replace(ep, steps=replace(ep.steps, proprio=proprio, action=action))


def _binary_gripper_dataset(*, chatter_in: tuple[int, ...]) -> list[Episode]:
    """Clean data whose last action channel is a proper binary gripper."""
    episodes = _synth.clean_dataset(n_episodes=12)
    out: list[Episode] = []
    for i, ep in enumerate(episodes):
        action = np.array(ep.steps.action, copy=True)
        n = action.shape[0]
        gripper = np.zeros(n)
        gripper[n // 2 :] = 1.0  # one intentional close, mid-episode
        if i in chatter_in:
            gripper[10:30] = np.arange(20) % 2  # rapid toggling
        action[:, -1] = gripper
        out.append(replace(ep, steps=replace(ep.steps, action=action)))
    return out
