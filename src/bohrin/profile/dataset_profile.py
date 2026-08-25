"""The ``DatasetProfile`` and its single-pass builder — Stage ③ (docs/02 §3).

The profile is the shared, precomputed statistical substrate every detector reads, so no
detector re-scans the data. It is built in **one streaming pass** that maintains, per
channel: online moments (Welford), a bounded uniform **reservoir** of rows (for quantiles,
histograms, and coverage), min/max, and zero-fraction. Streaming quantiles (q01/q50/q99)
are estimated from the reservoir — statistically valid because the reservoir is a uniform
sample — which keeps RAM O(reservoir), not O(dataset).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bohrin._arrays import FloatArray
from bohrin.ir.episode import Episode
from bohrin.ir.schema import DatasetSchema, SchemaHints
from bohrin.profile.online import Reservoir, RunningMoments

# Rows retained per channel for quantile/histogram/coverage estimation.
DEFAULT_RESERVOIR_ROWS = 20_000

_QUANTILES = (0.01, 0.5, 0.99)


@dataclass(frozen=True, slots=True)
class ChannelStats:
    """Per-channel statistics for one signal (action or proprio)."""

    mean: FloatArray
    std: FloatArray
    min: FloatArray
    max: FloatArray
    zero_fraction: FloatArray
    q01: FloatArray
    q50: FloatArray
    q99: FloatArray
    sample: FloatArray  # (M, D) reservoir rows — the bounded working set

    @property
    def dim(self) -> int:
        """Channel dimensionality (D)."""
        return int(self.mean.shape[0])


@dataclass(frozen=True, slots=True)
class DatasetProfile:
    """Precomputed statistics over a (sampled) dataset — read by every detector."""

    schema: DatasetSchema
    hints: SchemaHints
    n_episodes: int
    total_steps: int
    action: ChannelStats
    proprio: ChannelStats | None
    episode_lengths: tuple[int, ...]
    has_images: bool
    has_timestamps: bool
    control_hz: float | None
    #: Mean ‖action[t+1] − action[t]‖ over consecutive steps, or ``None`` when unmeasurable.
    #:
    #: A *temporal* statistic, which the reservoir cannot provide (it holds a uniform sample of
    #: rows, not consecutive ones), so it is accumulated during the streaming pass. It exists to
    #: tell deltas from absolute poses reliably — see
    #: :func:`bohrin.profile.action_space.infer_action_space`.
    action_step_norm: float | None = None

    @property
    def action_dim(self) -> int:
        """Action dimensionality (A)."""
        return self.action.dim

    @property
    def has_proprio(self) -> bool:
        """Whether proprioception is present."""
        return self.proprio is not None


class _ChannelAccumulator:
    """Online moments + reservoir for a single channel."""

    def __init__(self, capacity: int, rng: np.random.Generator) -> None:
        self._moments = RunningMoments()
        self._reservoir = Reservoir(capacity, rng)
        self._seen_any = False

    def update(self, batch: FloatArray) -> None:
        """Fold a batch in, excluding rows that contain NaN/±inf.

        **The profile must describe the finite data, or it describes nothing.** Welford's
        recurrence propagates a single NaN into that channel's mean *and* variance, and ±inf
        poisons min/max — after which every downstream statistic is NaN. Since roughly fifteen
        detectors read this profile rather than the raw episodes, one corrupt cell used to
        produce a cascade of spurious findings (measured: a single NaN added five, including a
        false ``stats.dead_dimension`` and a false ``stats.distribution_drift``) while the real
        problem was reported once by ``integrity.nan_inf``. Silent wrongness at this scale is
        worse than a crash, because the report looks plausible.

        Corruption is *not* hidden by this: it is detected on the raw episodes by the INTEGRITY
        family, which is the layer that owns it, and ``total_steps``/episode lengths still count
        every row.
        """
        rows = np.asarray(batch, dtype=np.float64)
        if rows.ndim == 2 and rows.size:
            finite = np.isfinite(rows).all(axis=1)
            if not bool(finite.all()):
                rows = rows[finite]
        if rows.shape[0] == 0:
            return
        self._moments.update(rows)
        self._reservoir.update(rows)
        self._seen_any = True

    @property
    def seen_any(self) -> bool:
        return self._seen_any

    def finalize(self) -> ChannelStats:
        sample = self._reservoir.values()
        if sample.shape[0] > 0:
            q01, q50, q99 = (np.quantile(sample, q, axis=0).astype(np.float64) for q in _QUANTILES)
        else:
            zeros = self._moments.mean
            q01 = q50 = q99 = zeros
        return ChannelStats(
            mean=self._moments.mean,
            std=self._moments.std,
            min=self._moments.min,
            max=self._moments.max,
            zero_fraction=self._moments.zero_fraction,
            q01=q01,
            q50=q50,
            q99=q99,
            sample=sample,
        )


class ProfileBuilder:
    """Accumulates a :class:`DatasetProfile` over a stream of episodes (one pass)."""

    def __init__(
        self,
        schema: DatasetSchema,
        hints: SchemaHints,
        rng: np.random.Generator,
        *,
        reservoir_rows: int = DEFAULT_RESERVOIR_ROWS,
    ) -> None:
        self._schema = schema
        self._hints = hints
        self._action = _ChannelAccumulator(reservoir_rows, rng)
        self._proprio = _ChannelAccumulator(reservoir_rows, rng)
        self._episode_lengths: list[int] = []
        self._total_steps = 0
        self._has_images = False
        self._has_timestamps = False
        self._dt_samples: list[float] = []
        self._step_norm_sum = 0.0
        self._step_norm_count = 0

    def add(self, episode: Episode) -> None:
        """Fold one episode into the running profile.

        Channels whose dimensionality disagrees with the schema are *not* folded into the
        stats (they would corrupt the aggregate); ``integrity.shape_dtype`` reports them
        separately from the raw episodes. This keeps the profile robust to ragged data.
        """
        steps = episode.steps
        action = np.asarray(steps.action, dtype=np.float64)
        if action.shape[1] == self._schema.action_dim:
            self._action.update(action)
            self._accumulate_step_norm(action)
        self._episode_lengths.append(episode.length)
        self._total_steps += episode.length
        if steps.proprio is not None:
            proprio = np.asarray(steps.proprio, dtype=np.float64)
            if self._schema.proprio_dim is None or proprio.shape[1] == self._schema.proprio_dim:
                self._proprio.update(proprio)
        if steps.images:
            self._has_images = True
        if steps.timestamp is not None and steps.timestamp.shape[0] >= 2:
            self._has_timestamps = True
            diffs = np.diff(np.asarray(steps.timestamp, dtype=np.float64))
            positive = diffs[diffs > 0.0]
            if positive.size:
                self._dt_samples.append(float(np.median(positive)))

    def _accumulate_step_norm(self, action: FloatArray) -> None:
        """Fold this episode's consecutive-step action changes into the running mean.

        Kept inside the single streaming pass because it is the one statistic the reservoir
        cannot reconstruct: it needs rows that were *adjacent in time*.
        """
        if action.shape[0] < 2:
            return
        deltas = np.linalg.norm(np.diff(action, axis=0), axis=1)
        deltas = deltas[np.isfinite(deltas)]
        if deltas.size == 0:
            return
        self._step_norm_sum += float(deltas.sum())
        self._step_norm_count += int(deltas.size)

    def finalize(self) -> DatasetProfile:
        """Close out the pass and produce the immutable :class:`DatasetProfile`."""
        control_hz = self._schema.control_hz
        if control_hz is None and self._dt_samples:
            median_dt = float(np.median(self._dt_samples))
            if median_dt > 0:
                control_hz = 1.0 / median_dt
        return DatasetProfile(
            schema=self._schema,
            hints=self._hints,
            n_episodes=len(self._episode_lengths),
            total_steps=self._total_steps,
            action=self._action.finalize(),
            proprio=self._proprio.finalize() if self._proprio.seen_any else None,
            episode_lengths=tuple(self._episode_lengths),
            has_images=self._has_images,
            has_timestamps=self._has_timestamps,
            control_hz=control_hz,
            action_step_norm=(self._step_norm_sum / self._step_norm_count if self._step_norm_count else None),
        )
