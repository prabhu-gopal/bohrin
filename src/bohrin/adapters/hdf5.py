"""HDF5 adapters — robomimic and raw/custom layouts (docs/01 §2.3, docs/06 P3).

Two adapters share one reader:

* ``robomimic_hdf5`` — the well-known layout: ``data/demo_<i>/{actions,obs/*,...}`` with
  per-demo attributes, and optional ``mask/<split>`` datasets naming the demos in each
  split. Those masks are what make ``integrity.split_leakage`` checkable at all.
* ``raw_hdf5`` — any other HDF5 file. Group structure is discovered, not assumed, and the
  schema mapper resolves which array is which.

``h5py`` is an optional dependency (``bohrin[hdf5]``): it is imported lazily inside
``detect``/``open`` so a LeRobot user never pays for it, and its absence degrades to
"this adapter doesn't claim the path" rather than an import error at startup.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from bohrin._arrays import AnyArray
from bohrin.adapters._arraysource import ArraySourceHandle
from bohrin.adapters.base import Adapter, DatasetHandle
from bohrin.config import ScanConfig

if TYPE_CHECKING:
    pass

_HDF5_SUFFIXES = frozenset({".hdf5", ".h5"})
#: robomimic keeps every demonstration under this group.
_ROBOMIMIC_ROOT = "data"
_ROBOMIMIC_MASK = "mask"


def _h5py() -> Any:
    """Import ``h5py`` lazily, with an actionable message if it is missing."""
    try:
        import h5py
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError("reading HDF5 datasets requires the optional dependency: pip install 'bohrin[hdf5]'") from exc
    return h5py


def _available() -> bool:
    try:
        import h5py  # noqa: F401
    except ImportError:  # pragma: no cover - depends on the install
        return False
    return True


def _visit_arrays(group: Any, prefix: str = "") -> dict[str, tuple[int, ...]]:
    """Recursively collect ``path -> shape`` for every dataset under ``group``."""
    h5py = _h5py()
    out: dict[str, tuple[int, ...]] = {}
    for name, item in group.items():
        path = f"{prefix}/{name}" if prefix else name
        if isinstance(item, h5py.Dataset):
            out[path] = tuple(int(d) for d in item.shape)
        elif isinstance(item, h5py.Group):
            out.update(_visit_arrays(item, path))
    return out


class _Hdf5Source:
    """An :class:`EpisodeArrays` over one HDF5 file."""

    def __init__(self, path: Path, *, root: str | None) -> None:
        h5py = _h5py()
        self._file = h5py.File(path, "r")
        self._root = root
        container = self._file[root] if root and root in self._file else self._file
        self._container = container
        self._keys = self._discover_episodes(container)

    @staticmethod
    def _discover_episodes(container: Any) -> list[str]:
        h5py = _h5py()
        groups = [k for k, v in container.items() if isinstance(v, h5py.Group)]
        if groups:
            # Sort demo_0, demo_1, demo_10 numerically, not lexically — otherwise episode
            # order (and therefore any index-based finding) depends on the digit count.
            return sorted(groups, key=_natural_key)
        return ["/"]  # a flat file: the whole file is one episode

    def episode_keys(self) -> Sequence[str]:
        return self._keys

    def arrays(self, episode_key: str) -> Mapping[str, AnyArray]:
        group = self._container if episode_key == "/" else self._container[episode_key]
        shapes = _visit_arrays(group)
        return _LazyH5Mapping(group, tuple(shapes))

    def task_for(self, episode_key: str) -> str | None:
        group = self._container if episode_key == "/" else self._container[episode_key]
        for attr in ("language_instruction", "task", "instruction", "goal"):
            if attr in group.attrs:
                value = group.attrs[attr]
                return value.decode() if isinstance(value, bytes) else str(value)
        return None

    def splits(self) -> dict[str, list[str]]:
        """robomimic ``mask/<split>`` → demo keys. Empty when the file has no masks."""
        if _ROBOMIMIC_MASK not in self._file:
            return {}
        out: dict[str, list[str]] = {}
        for split, members in self._file[_ROBOMIMIC_MASK].items():
            out[str(split)] = [m.decode() if isinstance(m, bytes) else str(m) for m in members[:]]
        return out

    def close(self) -> None:
        self._file.close()


class _LazyH5Mapping(Mapping[str, "AnyArray"]):
    """Reads an HDF5 dataset only when its key is actually indexed.

    The mapper inspects *shapes* of everything but the pipeline reads only the few arrays
    it mapped, so materializing every camera per episode would be pure waste.
    """

    def __init__(self, group: Any, keys: tuple[str, ...]) -> None:
        self._group = group
        self._keys = keys

    def __getitem__(self, key: str) -> AnyArray:
        return np.asarray(self._group[key][:])

    def __iter__(self) -> Any:
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)


def _natural_key(name: str) -> tuple[int, str]:
    digits = "".join(ch for ch in name if ch.isdigit())
    return (int(digits) if digits else 0, name)


class _Hdf5Adapter(Adapter):
    """Shared implementation; subclasses only differ in detection and root group."""

    _root: str | None = None

    def detect(self, path: Path) -> float:
        raise NotImplementedError  # pragma: no cover - subclasses implement

    def open(self, path: Path, config: ScanConfig) -> DatasetHandle:
        source = _Hdf5Source(path, root=self._root)
        return ArraySourceHandle(
            source,
            adapter_name=self.name,
            uri=str(path),
            declared=config.schema_map.get("schema", {}) if config.schema_map else {},
            no_vision=config.no_vision,
            # robomimic's `mask/` groups are the only place any supported format states a
            # train/val boundary -- without them `integrity.split_leakage` cannot run.
            splits=source.splits(),
        )


class RobomimicHdf5Adapter(_Hdf5Adapter):
    """robomimic-style HDF5: ``data/demo_<i>/...`` with optional ``mask/`` splits."""

    name = "robomimic_hdf5"
    _root = _ROBOMIMIC_ROOT

    def detect(self, path: Path) -> float:
        if not path.is_file() or path.suffix.lower() not in _HDF5_SUFFIXES or not _available():
            return 0.0
        h5py = _h5py()
        try:
            with h5py.File(path, "r") as f:
                if _ROBOMIMIC_ROOT not in f:
                    return 0.0
                demos = list(f[_ROBOMIMIC_ROOT].keys())
                if not demos:
                    return 0.0
                # The `mask/` group is robomimic's signature; without it we still claim the
                # file, but leave room for a more specific adapter to outrank us.
                return 0.95 if _ROBOMIMIC_MASK in f else 0.8
        except OSError:
            return 0.0


class RawHdf5Adapter(_Hdf5Adapter):
    """Any other HDF5 file — structure discovered, roles resolved by the schema mapper."""

    name = "raw_hdf5"
    _root = None

    def detect(self, path: Path) -> float:
        if not path.is_file() or path.suffix.lower() not in _HDF5_SUFFIXES or not _available():
            return 0.0
        h5py = _h5py()
        try:
            with h5py.File(path, "r"):
                # A weak claim on purpose: robomimic must win when its layout is present.
                return 0.4
        except OSError:
            return 0.0
