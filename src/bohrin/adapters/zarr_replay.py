"""Zarr replay-buffer adapter — Diffusion Policy / UMI layout (docs/01 §2.4).

The Diffusion Policy codebase stores a whole dataset as one flat, concatenated buffer:

    <root>/data/<name>     (N_total_steps, ...)   every episode, end to end
    <root>/meta/episode_ends  (n_episodes,)       exclusive end offset of each episode

There are no per-episode groups — episode boundaries exist *only* in ``episode_ends``.
That single array is therefore the whole adapter: slice every ``data/*`` array on those
boundaries and the flat buffer becomes a stream of IR episodes.

``zarr`` is optional (``bohrin[zarr]``) and imported lazily, like the HDF5 adapter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from bohrin._arrays import AnyArray
from bohrin.adapters._arraysource import ArraySourceHandle
from bohrin.adapters.base import Adapter, DatasetHandle
from bohrin.config import ScanConfig

_DATA_GROUP = "data"
_META_GROUP = "meta"
_EPISODE_ENDS = "episode_ends"


def _zarr() -> Any:
    try:
        import zarr
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "reading Zarr replay buffers requires the optional dependency: pip install 'bohrin[zarr]'"
        ) from exc
    return zarr


def _available() -> bool:
    try:
        import zarr  # noqa: F401
    except ImportError:  # pragma: no cover - depends on the install
        return False
    return True


def episode_bounds(episode_ends: Sequence[int]) -> list[tuple[int, int]]:
    """Convert exclusive end offsets into ``(start, stop)`` pairs.

    Kept module-level and pure so the boundary arithmetic — the one place this format can
    silently corrupt every downstream finding — is directly testable without any Zarr.
    """
    bounds: list[tuple[int, int]] = []
    start = 0
    for end in episode_ends:
        stop = int(end)
        if stop > start:
            bounds.append((start, stop))
        start = stop
    return bounds


class _SliceMapping(Mapping[str, "AnyArray"]):
    """One episode's slice of the flat buffer; each array is read on access."""

    def __init__(self, group: Any, keys: tuple[str, ...], start: int, stop: int) -> None:
        self._group = group
        self._keys = keys
        self._start = start
        self._stop = stop

    def __getitem__(self, key: str) -> AnyArray:
        return np.asarray(self._group[key][self._start : self._stop])

    def __iter__(self) -> Any:
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)


class _ZarrSource:
    """An :class:`EpisodeArrays` over a Diffusion-Policy-style replay buffer."""

    def __init__(self, path: Path) -> None:
        zarr = _zarr()
        self._root = zarr.open(str(path), mode="r")
        self._data = self._root[_DATA_GROUP]
        self._keys = tuple(sorted(self._data.array_keys()))
        ends = np.asarray(self._root[_META_GROUP][_EPISODE_ENDS][:]).ravel().tolist()
        self._bounds = episode_bounds([int(e) for e in ends])

    def episode_keys(self) -> Sequence[str]:
        return [f"episode_{i:05d}" for i in range(len(self._bounds))]

    def arrays(self, episode_key: str) -> Mapping[str, AnyArray]:
        index = int(episode_key.rsplit("_", 1)[1])
        start, stop = self._bounds[index]
        return _SliceMapping(self._data, self._keys, start, stop)

    def task_for(self, episode_key: str) -> str | None:
        return None  # the replay-buffer layout carries no per-episode language label


class ZarrReplayBufferAdapter(Adapter):
    """Diffusion Policy / UMI Zarr replay buffer."""

    name = "zarr_replaybuffer"

    def detect(self, path: Path) -> float:
        if not path.is_dir() or not _available():
            return 0.0
        # The signature is structural, and cheap to check on the filesystem alone.
        if not (path / _DATA_GROUP).is_dir() or not (path / _META_GROUP).is_dir():
            return 0.0
        zarr = _zarr()
        try:
            root = zarr.open(str(path), mode="r")
            return 0.95 if _EPISODE_ENDS in root[_META_GROUP] else 0.0
        except (OSError, KeyError, ValueError):
            return 0.0

    def open(self, path: Path, config: ScanConfig) -> DatasetHandle:
        return ArraySourceHandle(
            _ZarrSource(path),
            adapter_name=self.name,
            uri=str(path),
            declared=config.schema_map.get("schema", {}) if config.schema_map else {},
            no_vision=config.no_vision,
        )
