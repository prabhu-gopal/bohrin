"""Episode-level embeddings — the representation COVERAGE/CONSISTENCY/LABEL reason over.

Two views of an episode, both format-agnostic and computed from the Canonical IR:

* :func:`shape_embedding` — the trajectory *resampled on normalized time*, flattened. It
  lives in state units, so distances between episodes mean "how differently was this task
  performed", which is what mode-collapse and DTW-outlier detection need.
* :func:`summary_embedding` — a compact behavioural fingerprint (start, end, extent, path
  length, duration, action statistics) used for kNN, redundancy and label checks.

A frozen visual encoder (DINOv2) would slot in here as an additional view when images are
present (``bohrin[vision]``, docs/09 §5); the proprio-only embedding is the zero-dependency
floor that always works.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from bohrin._arrays import FloatArray
from bohrin.analysis.shapes import path_length, resample
from bohrin.ir.episode import Episode

RESAMPLE_POINTS = 16


def trajectory(episode: Episode) -> FloatArray:
    """The episode's state trajectory (proprio when present, else the action stream)."""
    steps = episode.steps
    if steps.proprio is not None:
        return np.asarray(steps.proprio, dtype=np.float64)
    return np.asarray(steps.action, dtype=np.float64)


def finite_steps(rows: FloatArray) -> FloatArray:
    """Rows with no NaN/±inf, or the input unchanged when it is already clean.

    An episode's *fingerprint* should describe the steps that were actually recorded. A single
    corrupt step otherwise propagates through every aggregate below — ``mean``, ``std`` and
    ``max − min`` all become non-finite — so the whole episode's embedding turns to NaN and the
    episode drops out of COVERAGE/CONSISTENCY entirely. Excluding the step instead keeps the
    other ~99 % of the episode in the analysis; ``integrity.nan_inf`` reports the corruption.
    """
    if rows.size == 0:
        return rows
    mask = np.isfinite(rows).all(axis=1) if rows.ndim == 2 else np.isfinite(rows)
    if bool(mask.all()):
        return rows
    return rows[mask]


def shape_embedding(episode: Episode, *, points: int = RESAMPLE_POINTS) -> FloatArray:
    """Flattened, time-normalized trajectory — comparable across different durations."""
    traj = finite_steps(trajectory(episode))
    if traj.shape[0] == 0:
        traj = np.zeros((1, max(1, trajectory(episode).shape[1])), dtype=np.float64)
    return resample(traj, points).ravel()


def summary_embedding(episode: Episode) -> FloatArray:
    """A compact behavioural fingerprint of one episode."""
    raw = trajectory(episode)
    traj = finite_steps(raw)
    if traj.shape[0] == 0:  # an entirely corrupt episode: describe it as motionless, not NaN
        traj = np.zeros((1, max(1, raw.shape[1])), dtype=np.float64)
    action = finite_steps(np.asarray(episode.steps.action, dtype=np.float64))
    if action.shape[0] == 0:
        action = np.zeros((1, max(1, np.asarray(episode.steps.action).shape[1])), dtype=np.float64)
    return np.concatenate(
        [
            traj[0],
            traj[-1],
            traj.max(axis=0) - traj.min(axis=0),
            action.mean(axis=0),
            action.std(axis=0),
            np.array([path_length(traj), float(traj.shape[0])], dtype=np.float64),
        ]
    )


def initial_states(episodes: Sequence[Episode]) -> FloatArray:
    """The first state of every episode, stacked ``(N, D)``."""
    return np.vstack([trajectory(ep)[0] for ep in episodes]) if episodes else np.empty((0, 0))


def stack(
    episodes: Sequence[Episode],
    fn: Callable[[Episode], FloatArray] | None = None,
) -> FloatArray:
    """Stack per-episode embeddings into ``(N, D)`` using ``fn`` (default: summary).

    Ragged episodes (a differing action/proprio width) are truncated to the common width so
    one malformed episode cannot break the whole matrix — ``integrity.shape_dtype`` reports
    it separately.
    """
    if not episodes:
        return np.empty((0, 0), dtype=np.float64)
    builder = fn or summary_embedding
    rows = [np.asarray(builder(ep), dtype=np.float64) for ep in episodes]
    width = min(r.shape[0] for r in rows)
    return np.vstack([r[:width] for r in rows])


def standardize(matrix: FloatArray) -> FloatArray:
    """Z-score each column so no single dimension dominates a distance.

    Column statistics ignore NaN/±inf, which **confines corruption to the row it came from**.
    With plain ``mean``/``std`` a single non-finite cell makes that column's mean NaN, and the
    subtraction then turns the column NaN for *every* episode — so one bad value in one episode
    silently poisoned the embedding of all of them, and the downstream row filter had nothing
    left to keep. That produced spurious COVERAGE findings on datasets whose only real defect
    was a single NaN.
    """
    if matrix.size == 0:
        return matrix
    finite = np.isfinite(matrix)
    if not finite.all():
        # All-NaN columns have no location or scale; leave them at 0 rather than inventing one.
        safe = np.where(finite, matrix, np.nan)
        with np.errstate(invalid="ignore"):
            mean = np.nanmean(np.where(finite.any(axis=0), safe, 0.0), axis=0)
            std = np.nanstd(np.where(finite.any(axis=0), safe, 0.0), axis=0)
        mean = np.nan_to_num(mean, nan=0.0)
        std = np.nan_to_num(std, nan=1.0)
    else:
        mean = matrix.mean(axis=0)
        std = matrix.std(axis=0)
    std[std < 1e-12] = 1.0
    # Non-finite cells stay non-finite by design (the row filter downstream removes them), so
    # numpy's warning about them is noise rather than information.
    with np.errstate(invalid="ignore"):
        out: FloatArray = (matrix - mean) / std
    return out
