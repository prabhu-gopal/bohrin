"""Inferring what an action vector *means* from its distribution (docs/03 §2).

Whether actions are **deltas** (velocity-like increments) or **absolute poses** changes what
almost every temporal check should compare against, so this inference is not specific to the
POLICY↔DATA family that first needed it — ``temporal.action_observation_lag`` depends on it
too, and comparing the wrong pair of signals is how that detector produced a systematic false
positive on absolute-pose datasets. One implementation, in the layer that owns profile-derived
facts.
"""

from __future__ import annotations

import numpy as np

from bohrin._arrays import FloatArray
from bohrin.ir.schema import ActionSpace
from bohrin.profile.dataset_profile import DatasetProfile

#: Fraction of channels that must look centred (delta-like) or offset (absolute-like) before
#: we commit. Between the two the answer is UNKNOWN, deliberately.
_ABSOLUTE_FRAC = 0.9

#: Consecutive-step change, relative to the action's own spread, below which the signal is a
#: **smooth trajectory** (an absolute pose) rather than a sequence of increments.
#:
#: For deltas that are roughly independent step to step, ``E‖a[t+1] − a[t]‖ ≈ √2 · ‖σ‖``, so the
#: normalized ratio sits near 1. An absolute pose moves a small fraction of its own range each
#: step, driving the ratio far below 1. The gap between the two regimes is an order of
#: magnitude, so this is a far sharper discriminator than the location test below.
_SMOOTH_STEP_RATIO = 0.35

DELTA_SPACES = frozenset({ActionSpace.EEF_DELTA, ActionSpace.JOINT_VEL})
ABSOLUTE_SPACES = frozenset({ActionSpace.EEF_ABS, ActionSpace.JOINT_POS, ActionSpace.EEF_6D_ROT})


def _step_ratio(profile: DatasetProfile) -> float | None:
    """Mean consecutive-step action change ÷ ``√2 · ‖σ‖``, or ``None`` if unmeasurable."""
    step = profile.action_step_norm
    if step is None:
        return None
    std = np.asarray(profile.action.std, dtype=np.float64)
    spread = float(np.sqrt(np.sum(std**2)))
    if spread <= 1e-12:
        return None
    ratio: float = step / (float(np.sqrt(2.0)) * spread)
    return ratio


def infer_action_space(profile: DatasetProfile) -> ActionSpace:
    """Guess whether actions are deltas or absolute positions from their distribution.

    Two signals, in order of reliability:

    1. **Temporal smoothness** (:data:`_SMOOTH_STEP_RATIO`). An absolute pose trajectory changes
       by a small fraction of its own spread each step; independent deltas change by about their
       whole spread. This separates the two regimes by an order of magnitude.
    2. **Location.** Deltas are near-zero-mean relative to their spread, absolute poses are
       offset from zero.

    The location test alone is not sufficient, and relying on it was a real defect: absolute
    poses recorded around a workspace centred near the origin — or pooled across episodes with
    varied start offsets — have a near-zero mean and were confidently misread as deltas. Every
    action-space-aware check downstream then reverted to the wrong comparison, so an
    ``.npz`` dataset of joint positions still collected spurious CAUSAL and MULTIMODALITY HIGHs
    even after those detectors were taught about action spaces.

    Returns ``UNKNOWN`` when neither signal is clear — a wrong guess here produces a confident
    and completely wrong finding, so abstaining is the cheaper error.
    """
    stats = profile.action
    if stats.dim == 0:
        return ActionSpace.UNKNOWN

    ratio = _step_ratio(profile)
    if ratio is not None and ratio < _SMOOTH_STEP_RATIO:
        return ActionSpace.EEF_ABS

    mean = np.abs(np.asarray(stats.mean, dtype=np.float64))
    std = np.asarray(stats.std, dtype=np.float64)
    usable = std > 1e-9
    if not usable.any():
        return ActionSpace.UNKNOWN
    centered = mean[usable] < 0.5 * std[usable]
    frac = float(np.mean(centered))
    if frac >= _ABSOLUTE_FRAC:
        # Centred *and* not smooth: genuine increments.
        return ActionSpace.EEF_DELTA if ratio is None or ratio >= _SMOOTH_STEP_RATIO else ActionSpace.UNKNOWN
    if frac <= 1.0 - _ABSOLUTE_FRAC:
        return ActionSpace.EEF_ABS
    return ActionSpace.UNKNOWN


def resolve_action_space(profile: DatasetProfile, declared: ActionSpace) -> ActionSpace:
    """The declared action space, falling back to inference when it is ``UNKNOWN``."""
    return declared if declared is not ActionSpace.UNKNOWN else infer_action_space(profile)


def is_absolute(space: ActionSpace) -> bool:
    """Whether ``space`` describes an absolute pose/target rather than an increment."""
    return space in ABSOLUTE_SPACES


def action_increments(action: FloatArray, space: ActionSpace) -> FloatArray:
    """The action expressed as *motion commanded per step*, whatever the action space.

    For a delta/velocity space this is the action itself. For an absolute pose or joint target
    it is the first difference, because the increment is the part that carries the command —
    the absolute value is dominated by *where the robot happens to be*.

    **Why several detectors need this.** A number of checks are really about the commanded
    motion, and reading an absolute pose as though it were a motion makes them fire on the
    representation rather than on any defect:

    * ``causal.copycat_shortcut`` asks how predictable an action is from the previous action. A
      pose trajectory is smooth, so absolute targets are ~100 % autocorrelated *by construction*
      — a guaranteed HIGH on every ``JOINT_POS`` dataset, which is the most common kind.
    * ``causal.proprio_shortcut`` asks whether the action is a function of the current state.
      For absolute targets ``a_t ≈ o_t``, so the answer is trivially yes.
    * ``multimodality.contradictory_actions`` compares the actions taken at nearby states. With
      absolute targets those actions are nearly the state itself, which collapses the scale that
      decides whether two commands genuinely disagree.

    The last row is repeated so the result keeps the input's length, which matters wherever a
    row is paired with the state it was issued from.
    """
    a = np.asarray(action, dtype=np.float64)
    if not is_absolute(space) or a.shape[0] < 2:
        return a
    deltas: FloatArray = np.empty_like(a)
    deltas[:-1] = np.diff(a, axis=0)
    deltas[-1] = deltas[-2]
    return deltas
