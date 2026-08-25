"""The Canonical IR episode model (docs/03 §1, §3).

Adapters write these; detectors read them; nothing else. Low-dim signals (action,
proprio, timestamp, reward) are materialized as contiguous numpy columns when an episode
is opened — cheap. Heavy modalities (images, depth, point clouds) are **lazy handles**
decoded only if a vision detector actually asks, so a stats-only scan never touches video.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from bohrin._arrays import FloatArray
from bohrin.ir.schema import Provenance


@runtime_checkable
class LazyImage(Protocol):
    """A decode-on-demand image frame. ``shape`` is known without decoding."""

    @property
    def shape(self) -> tuple[int, int, int]:  # (H, W, C)
        ...

    def array(self) -> FloatArray:
        """Decode the frame (video frame / HDF5 chunk) to an ``(H, W, C)`` array."""
        ...


@runtime_checkable
class LazyArray(Protocol):
    """A decode-on-demand n-D array (e.g. a point cloud)."""

    @property
    def shape(self) -> tuple[int, ...]: ...

    def array(self) -> FloatArray: ...


@dataclass(frozen=True, slots=True)
class TaskLabel:
    """A natural-language instruction and/or an integer task id."""

    text: str | None = None
    task_id: int | None = None


@dataclass(frozen=True, slots=True)
class Step:
    """A single logical row of an episode (physically a slice of the columnar StepView)."""

    t: int
    action: FloatArray  # (A,)
    timestamp: float | None = None
    proprio: FloatArray | None = None  # (P,)
    images: Mapping[str, LazyImage] = field(default_factory=dict)
    depth: Mapping[str, LazyImage] = field(default_factory=dict)
    point_cloud: LazyArray | None = None
    reward: float | None = None
    extras: Mapping[str, FloatArray] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StepView:
    """Columnar, lazy view over an episode's steps (docs/03 §3).

    ``action`` is the only required column — the one field every imitation dataset has.
    Everything else is optional, and its *absence* is itself information.
    """

    action: FloatArray  # (T, A)  REQUIRED
    timestamp: FloatArray | None = None  # (T,)
    proprio: FloatArray | None = None  # (T, P)
    reward: FloatArray | None = None  # (T,)
    images: Mapping[str, Sequence[LazyImage]] = field(default_factory=dict)
    depth: Mapping[str, Sequence[LazyImage]] = field(default_factory=dict)
    point_cloud: Sequence[LazyArray] | None = None

    def __post_init__(self) -> None:
        if self.action.ndim != 2:
            raise ValueError(f"action column must be 2-D (T, A); got shape {self.action.shape}")

    def __len__(self) -> int:
        return int(self.action.shape[0])

    @property
    def length(self) -> int:
        """Number of steps (T)."""
        return int(self.action.shape[0])

    @property
    def action_dim(self) -> int:
        """Action dimensionality (A)."""
        return int(self.action.shape[1])

    def step(self, t: int) -> Step:
        """Materialize a single :class:`Step` view at index ``t`` (no heavy decode)."""
        return Step(
            t=t,
            action=self.action[t],
            timestamp=None if self.timestamp is None else float(self.timestamp[t]),
            proprio=None if self.proprio is None else self.proprio[t],
            reward=None if self.reward is None else float(self.reward[t]),
            images={k: frames[t] for k, frames in self.images.items()},
            depth={k: frames[t] for k, frames in self.depth.items()},
            point_cloud=None if self.point_cloud is None else self.point_cloud[t],
        )


@dataclass(frozen=True, slots=True)
class Episode:
    """One demonstration trajectory in the Canonical IR (docs/03 §1)."""

    episode_id: str
    steps: StepView
    source: Provenance
    task: TaskLabel | None = None
    success: bool | None = None
    #: Declared train/val/test membership, when the source states it (robomimic ``mask/``).
    #: Optional by design: most formats have no notion of a split, and absence is honest —
    #: it is what makes ``integrity.split_leakage`` stay silent rather than invent a split.
    split: str | None = None

    def __post_init__(self) -> None:
        if self.length <= 0:
            raise ValueError(f"episode {self.episode_id!r} has no steps")

    @property
    def length(self) -> int:
        """Number of steps in the episode."""
        return self.steps.length
