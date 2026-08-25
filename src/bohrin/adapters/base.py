"""The adapter contract — Stage ① (docs/02 §1).

An adapter is the *only* code that touches a format-specific container. It turns any
on-disk dataset into a stream of Canonical IR episodes. Adding a format is one class and
one entry point; detectors, synthesis, and the report never change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

from bohrin.ir.episode import Episode
from bohrin.ir.schema import DatasetSchema, SchemaHints

if TYPE_CHECKING:
    from bohrin._arrays import IntArray
    from bohrin.config import ScanConfig


@dataclass(frozen=True, slots=True)
class Sampler:
    """Deterministic episode subsampling for triage runs (docs/02 §7).

    ``plan(total)`` returns the sorted episode indices to keep. With a fixed ``seed`` the
    selection is reproducible, so two scans of the same data agree (docs/02 §9).
    """

    max_episodes: int | None = None
    seed: int = 0

    def plan(self, total: int) -> IntArray:
        """Sorted indices of the episodes to keep from ``total`` available."""
        if total <= 0:
            return np.empty(0, dtype=np.int64)
        keep = total if self.max_episodes is None else min(self.max_episodes, total)
        if keep >= total:
            return np.arange(total, dtype=np.int64)
        rng = np.random.default_rng(self.seed)
        chosen = rng.choice(total, size=keep, replace=False)
        chosen.sort()
        return chosen.astype(np.int64)

    def keeps(self, index: int, total: int) -> bool:
        """Whether episode ``index`` survives the plan (for streaming adapters)."""
        return bool(index in set(self.plan(total).tolist()))


@runtime_checkable
class DatasetHandle(Protocol):
    """An opened dataset: its schema, declared hints, and a streaming episode iterator."""

    def schema(self) -> DatasetSchema:
        """The frozen, dataset-wide type description (docs/03 §2)."""
        ...

    def profile_hints(self) -> SchemaHints:
        """Declared dtypes/shapes/stats from the source, if any (docs/03 §5)."""
        ...

    def episode_count(self) -> int | None:
        """Episode count if known cheaply, else ``None``."""
        ...

    def iter_episodes(self, *, sample: Sampler) -> Iterator[Episode]:
        """Stream episodes (honoring ``sample``). STREAMING — never loads all at once."""
        ...


class Adapter(ABC):
    """Base class for every format adapter. Register via the ``bohrin.adapters`` group."""

    #: Stable identifier, e.g. ``"lerobot_v3"``. Set on the subclass.
    name: str = ""

    @abstractmethod
    def detect(self, path: Path) -> float:
        """Confidence in ``[0, 1]`` that ``path`` is this adapter's format (cheap check)."""
        raise NotImplementedError

    @abstractmethod
    def open(self, path: Path, config: ScanConfig) -> DatasetHandle:
        """Open ``path`` and return a streaming :class:`DatasetHandle`."""
        raise NotImplementedError
