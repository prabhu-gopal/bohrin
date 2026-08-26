"""The light inverse/forward dynamics model — Stage ③.6 (docs/02 §3.6, docs/07 §3).

Fits a cheap, **cross-validated** dynamics model on proprioception + action and exposes the
per-transition residual as a shared input the DYNAMICS detectors consume, the same way
other detectors consume the Profile.

* **Inverse** ``g(oₜ, oₜ₊₁) → âₜ`` — a large residual means the logged action does *not*
  explain the observed state change: corrupt/mislabeled actions, action↔observation
  misalignment, or a physically impossible transition.
* **Forward** ``f(oₜ, aₜ) → ôₜ₊₁`` — the complementary view, catching the same defects from
  the prediction side.

Residuals are **out-of-fold** (K-fold cross-validated), so a large residual reflects genuine
*inconsistency* with the rest of the dataset rather than model underfit. Ridge regression
keeps it fast and dependency-light; the residual, not the model, is the product.

Grounded in inverse-dynamics action labeling (arXiv 2412.15109).
"""

from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.linalg import LinAlgWarning
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from bohrin._arrays import FloatArray, IntArray
from bohrin.analysis.robust import finite_row_mask
from bohrin.ir.episode import Episode

_MIN_TRANSITIONS = 64

#: Ridge penalty for the dynamics fits, applied to **standardized** features.
#:
#: The design matrix stacks ``(state[t-1], state[t], state[t+1])``, and in a smooth trajectory
#: those columns are nearly identical, so the matrix is collinear by construction. The previous
#: value (1e-6) left that collinearity essentially unregularized: scikit-learn's own guidance is
#: that an alpha near zero is numerically inadvisable, and in practice LAPACK reported
#: ``Ill-conditioned matrix (rcond=7e-17)`` on real datasets, which leaked to stderr and — more
#: importantly — meant the residual the DYNAMICS detectors threshold was computed from a fit
#: that LAPACK itself flagged as unreliable.
#:
#: Standardizing first (see :func:`_fit_out_of_fold`) puts every column on a comparable scale,
#: which is what makes a single alpha meaningful across datasets whose units differ by orders of
#: magnitude. 1.0 is a mild penalty on standardized columns: enough to condition the solve,
#: small enough that a genuinely inconsistent transition still leaves a large residual.
_RIDGE_ALPHA = 1.0


@dataclass(frozen=True, slots=True)
class DynamicsFit:
    """Out-of-fold residuals for every usable transition in the reservoir."""

    residuals: FloatArray  # (K,) per-transition residual norm
    owner: IntArray  # (K,) index of the episode each transition came from
    r2: float  # out-of-fold R² of the fit (diagnostic)
    target_scale: float  # median magnitude of the predicted quantity

    @property
    def n_transitions(self) -> int:
        """Number of transitions the model was evaluated on."""
        return int(self.residuals.shape[0])

    @property
    def relative(self) -> FloatArray:
        """Residual as a fraction of the signal being predicted.

        This is what makes the check work when the dynamics fit is near-perfect: the MAD of
        the residuals is then degenerate, so a purely relative-to-siblings z-score would see
        nothing. A residual as large as the signal itself means the model cannot explain the
        transition at all, regardless of how tight the rest of the fit is.
        """
        scale = self.target_scale if self.target_scale > 1e-12 else 1.0
        out: FloatArray = self.residuals / scale
        return out


def _transitions(
    episodes: Sequence[Episode],
) -> tuple[FloatArray, FloatArray, FloatArray, FloatArray, FloatArray, IntArray]:
    """Collect ``(state_t-1, state_t, state_t+1, action_t, owner)`` per episode (no cross-boundary).

    The **previous** state is carried alongside the transition so the models below can express
    any of the legitimate action/state row-indexing conventions. Without it, a dataset logging
    ``action[t] = state[t] − state[t−1]`` — an ordinary and correct convention — is
    unexplainable by construction: the quantity being predicted depends on a state the model was
    never shown, so every transition looks like a physics violation and
    ``dynamics.inverse_residual`` reported a dataset-wide HIGH on correctly-recorded data.
    """
    s_prev: list[FloatArray] = []
    s_t: list[FloatArray] = []
    s_next: list[FloatArray] = []
    a_t: list[FloatArray] = []
    a_next: list[FloatArray] = []
    owner: list[IntArray] = []
    for i, ep in enumerate(episodes):
        proprio = ep.steps.proprio
        if proprio is None:
            continue
        state = np.asarray(proprio, dtype=np.float64)
        action = np.asarray(ep.steps.action, dtype=np.float64)
        if state.shape[0] < 3 or action.shape[0] != state.shape[0]:
            continue
        # Index t runs over 1 … T-2 so that t-1 and t+1 both exist.
        s_prev.append(state[:-2])
        s_t.append(state[1:-1])
        s_next.append(state[2:])
        a_t.append(action[1:-1])
        a_next.append(action[2:])
        owner.append(np.full(state.shape[0] - 2, i, dtype=np.int64))
    if not s_t:
        empty = np.empty((0, 0), dtype=np.float64)
        return empty, empty, empty, empty, empty, np.empty(0, dtype=np.int64)
    widths = min(x.shape[1] for x in s_t)
    a_width = min(x.shape[1] for x in a_t)
    previous = np.vstack([x[:, :widths] for x in s_prev])
    state = np.vstack([x[:, :widths] for x in s_t])
    state_next = np.vstack([x[:, :widths] for x in s_next])
    action = np.vstack([x[:, :a_width] for x in a_t])
    action_next = np.vstack([x[:, :a_width] for x in a_next])
    owners = np.concatenate(owner)
    # Ridge raises on NaN/inf, which aborted the scan for both DYNAMICS detectors on any
    # dataset containing one. Drop those transitions and fit on the rest; `owner` is filtered
    # in step so a residual still maps back to the episode it came from.
    mask = finite_row_mask(previous, state, state_next, action, action_next)
    if not bool(mask.all()):
        previous, state, state_next, action, action_next, owners = (
            previous[mask],
            state[mask],
            state_next[mask],
            action[mask],
            action_next[mask],
            owners[mask],
        )
    return previous, state, state_next, action, action_next, owners


def _fit_out_of_fold(features: FloatArray, targets: FloatArray, folds: int) -> tuple[FloatArray, float] | None:
    """K-fold out-of-fold predictions → per-row residual norms and overall R², or ``None``.

    Returns ``None`` when the solve is numerically unreliable, so the DYNAMICS detectors
    **abstain** rather than threshold a residual computed from a fit LAPACK flagged as
    ill-conditioned. Abstaining is the cheaper error: a confident finding derived from a
    broken fit is worse than no finding, and this detector family's severity was already
    under review for over-reporting.

    Two changes make that rare rather than routine. Features are **standardized inside each
    fold** (fit on train, applied to test, so no leakage), which matters because the raw
    columns are joint angles, velocities, and gripper states whose units differ by orders of
    magnitude. And the ridge penalty is :data:`_RIDGE_ALPHA` rather than a token 1e-6, which
    is what actually conditions the collinear ``(state[t-1], state[t], state[t+1])`` block.

    ``np.errstate`` suppresses FPE flags raised inside BLAS during ``X.T @ X``; those are an
    internal artifact, not a statement about our input, and the caller already filtered
    non-finite rows.
    """
    n = features.shape[0]
    k = max(2, min(folds, n // 2))
    predictions = np.zeros_like(targets)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"), warnings.catch_warnings():
        # Promote LAPACK's ill-conditioning warning to an exception so it becomes an
        # abstention here instead of stderr noise in the user's terminal.
        warnings.simplefilter("error", LinAlgWarning)
        try:
            for train_idx, test_idx in KFold(n_splits=k, shuffle=False).split(features):
                model = make_pipeline(StandardScaler(), Ridge(alpha=_RIDGE_ALPHA))
                model.fit(features[train_idx], targets[train_idx])
                predictions[test_idx] = model.predict(features[test_idx])
        except LinAlgWarning:
            return None
    if not np.isfinite(predictions).all():
        return None
    residual = np.linalg.norm(targets - predictions, axis=1).astype(np.float64)
    ss_res = float(np.sum((targets - predictions) ** 2))
    ss_tot = float(np.sum((targets - targets.mean(axis=0)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
    return residual, r2


def fit_inverse_dynamics(episodes: Sequence[Episode], *, folds: int = 4) -> DynamicsFit | None:
    """Fit ``g(oₜ₋₁, oₜ, oₜ₊₁) → âₜ`` and return out-of-fold residuals, or ``None`` if infeasible.

    Both surrounding state changes are supplied, so the fit can express ``action[t]`` as either
    the delta that *produced* ``oₜ`` or the one that produces ``oₜ₊₁`` — the two conventions —
    and only a genuinely inconsistent transition leaves a large residual.
    """
    s_prev, s_t, s_next, a_t, _, owner = _transitions(episodes)
    if s_t.shape[0] < _MIN_TRANSITIONS:
        return None
    features = np.hstack([s_prev, s_t, s_next, s_t - s_prev, s_next - s_t])
    fit = _fit_out_of_fold(features, a_t, folds)
    if fit is None:  # numerically unreliable solve — abstain rather than report from it
        return None
    residual, r2 = fit
    scale = float(np.median(np.linalg.norm(a_t, axis=1)))
    return DynamicsFit(residuals=residual, owner=owner, r2=r2, target_scale=scale)


def fit_forward_dynamics(episodes: Sequence[Episode], *, folds: int = 4) -> DynamicsFit | None:
    """Fit ``f(oₜ₋₁, oₜ, aₜ, aₜ₊₁) → Δoₜ``; out-of-fold residuals, or ``None`` if infeasible.

    Both the current and the *next* action are supplied, which is what makes the check
    convention-agnostic. The premise "the logged action tells you the coming state change" holds
    for ``aₜ`` under a forward-difference convention and for ``aₜ₊₁`` under a backward one; given
    only ``aₜ``, a correctly-recorded backward-convention dataset is unexplainable by
    construction and every transition was reported as physically inconsistent. A genuine
    teleport still leaves a large residual, because *no* action accounts for it.
    """
    s_prev, s_t, s_next, a_t, a_next, owner = _transitions(episodes)
    if s_t.shape[0] < _MIN_TRANSITIONS:
        return None
    features = np.hstack([s_prev, s_t, a_t, a_next])
    delta = s_next - s_t
    fit = _fit_out_of_fold(features, delta, folds)
    if fit is None:  # numerically unreliable solve — abstain rather than report from it
        return None
    residual, r2 = fit
    scale = float(np.median(np.linalg.norm(delta, axis=1)))
    return DynamicsFit(residuals=residual, owner=owner, r2=r2, target_scale=scale)
