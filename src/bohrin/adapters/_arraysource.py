"""Shared machinery for adapters whose source is "a bag of named arrays".

HDF5, NumPy directories and Zarr replay buffers differ in *how* you list and slice arrays,
but not in what happens next: run the schema mapper, slice per episode, wrap in a
:class:`StepView`. That common half lives here so the three adapters stay thin and the IR
construction is written — and tested — exactly once.

The contract a concrete adapter implements is :class:`EpisodeArrays`: given an episode
index, hand back its arrays. Everything else (mapping, dtype coercion, camera specs,
provenance) is done for it.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from bohrin._arrays import AnyArray, FloatArray
from bohrin.adapters._mapping import ArrayInfo, SchemaMapping, infer_mapping
from bohrin.adapters.base import Sampler
from bohrin.ir.episode import Episode, StepView, TaskLabel
from bohrin.ir.schema import ActionSpace, CameraSpec, DatasetSchema, Provenance, SchemaHints


class EpisodeArrays(Protocol):
    """A source of per-episode named arrays."""

    def episode_keys(self) -> Sequence[str]:
        """Stable identifiers for each episode, in order."""
        ...

    def arrays(self, episode_key: str) -> Mapping[str, AnyArray]:
        """The named arrays for one episode. Called lazily, one episode at a time."""
        ...

    def task_for(self, episode_key: str) -> str | None:
        """The language instruction for this episode, if the format carries one."""
        ...


@dataclass(frozen=True, slots=True)
class _ImageFrames:
    """A lazy per-frame view over a ``(T, H, W[, C])`` array — satisfies ``LazyImage``."""

    data: AnyArray
    index: int

    @property
    def shape(self) -> tuple[int, int, int]:
        frame = self.data[self.index]
        if frame.ndim == 2:
            return (int(frame.shape[0]), int(frame.shape[1]), 1)
        return (int(frame.shape[0]), int(frame.shape[1]), int(frame.shape[2]))

    def array(self) -> FloatArray:
        frame = np.asarray(self.data[self.index], dtype=np.float64)
        return frame if frame.ndim == 3 else frame[:, :, None]


def _as_2d(arr: AnyArray) -> FloatArray:
    """Coerce a per-step signal to ``(T, D)`` float64 — the IR's low-dimensional shape."""
    out = np.asarray(arr, dtype=np.float64)
    if out.ndim == 1:
        return out.reshape(-1, 1)
    if out.ndim > 2:  # flatten trailing dims, e.g. (T, 2, 3) poses → (T, 6)
        return out.reshape(out.shape[0], -1)
    return out


def _as_1d(arr: AnyArray) -> FloatArray:
    out = np.asarray(arr, dtype=np.float64).ravel()
    return out


def build_schema(
    mapping: SchemaMapping,
    sample: Mapping[str, AnyArray],
    *,
    control_hz: float | None,
    embodiment: str | None,
) -> DatasetSchema:
    """Derive the dataset-wide schema from one representative episode."""
    action = _as_2d(sample[mapping.action])
    proprio = _as_2d(sample[mapping.proprio]) if mapping.proprio is not None and mapping.proprio in sample else None
    cameras = tuple(
        CameraSpec(key=key, height=int(sample[key].shape[1]), width=int(sample[key].shape[2]))
        for key in mapping.images
        if key in sample and sample[key].ndim >= 3
    )
    return DatasetSchema(
        action_dim=int(action.shape[1]),
        action_space=ActionSpace.UNKNOWN,  # custom containers rarely declare it; stay honest
        proprio_dim=None if proprio is None else int(proprio.shape[1]),
        cameras=cameras,
        control_hz=control_hz,
        embodiment=embodiment,
    )


def infer_control_hz(sample: Mapping[str, AnyArray], mapping: SchemaMapping) -> float | None:
    """Estimate the control rate from timestamps, if the source has any."""
    if mapping.timestamp is None or mapping.timestamp not in sample:
        return None
    ts = _as_1d(sample[mapping.timestamp])
    if ts.size < 2:
        return None
    dt = float(np.median(np.diff(ts)))
    return 1.0 / dt if dt > 0 else None


class ArraySourceHandle:
    """A :class:`DatasetHandle` over any :class:`EpisodeArrays` source."""

    def __init__(
        self,
        source: EpisodeArrays,
        *,
        adapter_name: str,
        uri: str,
        declared: Mapping[str, object] | None = None,
        embodiment: str | None = None,
        no_vision: bool = False,
        hints: SchemaHints | None = None,
        splits: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        self._source = source
        self._adapter_name = adapter_name
        self._uri = uri
        self._no_vision = no_vision
        # episode key -> declared split name, inverted once so lookup is O(1) per episode.
        self._split_of: dict[str, str] = {key: name for name, members in (splits or {}).items() for key in members}
        self._hints = hints or SchemaHints.empty()
        self._keys = list(source.episode_keys())
        if not self._keys:
            raise ValueError(f"{adapter_name}: no episodes found in {uri}")

        first = source.arrays(self._keys[0])
        infos = [ArrayInfo(key=k, shape=tuple(int(d) for d in v.shape)) for k, v in first.items()]
        self._mapping = infer_mapping(infos, declared)
        hz = infer_control_hz(first, self._mapping)
        self._schema = build_schema(self._mapping, first, control_hz=hz, embodiment=embodiment)

    @property
    def mapping(self) -> SchemaMapping:
        """The resolved role→key mapping (exposed for ``bohrin init`` and tests)."""
        return self._mapping

    def schema(self) -> DatasetSchema:
        return self._schema

    def profile_hints(self) -> SchemaHints:
        return self._hints

    def episode_count(self) -> int | None:
        return len(self._keys)

    def iter_episodes(self, *, sample: Sampler) -> Iterator[Episode]:
        keep = set(sample.plan(len(self._keys)).tolist())
        for index, key in enumerate(self._keys):
            if index not in keep:
                continue
            yield self._episode(index, key)

    def _episode(self, index: int, key: str) -> Episode:
        arrays = self._source.arrays(key)
        m = self._mapping
        action = _as_2d(arrays[m.action])
        n_steps = action.shape[0]

        images: dict[str, Sequence[_ImageFrames]] = {}
        depth: dict[str, Sequence[_ImageFrames]] = {}
        if not self._no_vision:
            for cam in m.images:
                if cam in arrays:
                    images[cam] = [_ImageFrames(arrays[cam], t) for t in range(min(n_steps, len(arrays[cam])))]
            for cam in m.depth:
                if cam in arrays:
                    depth[cam] = [_ImageFrames(arrays[cam], t) for t in range(min(n_steps, len(arrays[cam])))]

        steps = StepView(
            action=action,
            timestamp=_as_1d(arrays[m.timestamp]) if m.timestamp and m.timestamp in arrays else None,
            proprio=_as_2d(arrays[m.proprio]) if m.proprio and m.proprio in arrays else None,
            reward=_as_1d(arrays[m.reward]) if m.reward and m.reward in arrays else None,
            images=images,
            depth=depth,
        )
        task = self._source.task_for(key)
        return Episode(
            episode_id=key,
            steps=steps,
            source=Provenance(adapter=self._adapter_name, uri=self._uri, locator=key),
            task=None if task is None else TaskLabel(text=task),
            split=self._split_of.get(key),
        )
