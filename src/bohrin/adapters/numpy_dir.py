"""NumPy directory adapter — one ``.npz`` (or ``.npy`` set) per episode (docs/01 §2.5).

The lowest-common-denominator format: a folder of files a researcher saved with
``np.savez``. There is no declared schema at all, so the whole job is the schema mapper.
Uses only NumPy, which is already a core dependency — no extra to install.

``.npz`` is read with ``mmap``-friendly lazy member access: ``np.load`` returns a lazy
archive, so listing shapes does not decode every camera.
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

_EPISODE_SUFFIXES = (".npz",)
#: Directories with more episode files than this are still fine — the cap only bounds how
#: many we inspect while *detecting* the format.
_DETECT_SCAN_LIMIT = 4


def _episode_files(path: Path) -> list[Path]:
    return sorted((p for p in path.iterdir() if p.suffix.lower() in _EPISODE_SUFFIXES), key=_natural_key)


def _natural_key(path: Path) -> tuple[int, str]:
    digits = "".join(ch for ch in path.stem if ch.isdigit())
    return (int(digits) if digits else 0, path.name)


class _NpzMapping(Mapping[str, "AnyArray"]):
    """Lazy view over one ``.npz`` archive: members decode on first access."""

    def __init__(self, path: Path) -> None:
        self._archive = np.load(path, allow_pickle=False, mmap_mode=None)
        self._keys = tuple(self._archive.files)

    def __getitem__(self, key: str) -> AnyArray:
        return np.asarray(self._archive[key])

    def __iter__(self) -> Any:
        return iter(self._keys)

    def __len__(self) -> int:
        return len(self._keys)


class _NumpyDirSource:
    """An :class:`EpisodeArrays` over a directory of ``.npz`` episodes."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._files = _episode_files(root)

    def episode_keys(self) -> Sequence[str]:
        return [p.name for p in self._files]

    def arrays(self, episode_key: str) -> Mapping[str, AnyArray]:
        return _NpzMapping(self._root / episode_key)

    def task_for(self, episode_key: str) -> str | None:
        """A sibling ``<episode>.txt`` holds the instruction, if the recorder wrote one."""
        sidecar = (self._root / episode_key).with_suffix(".txt")
        if sidecar.is_file():
            text = sidecar.read_text(encoding="utf-8").strip()
            return text or None
        return None


class NumpyDirAdapter(Adapter):
    """A directory of per-episode ``.npz`` files."""

    name = "numpy_dir"

    def detect(self, path: Path) -> float:
        if not path.is_dir():
            return 0.0
        files = _episode_files(path)
        if not files:
            return 0.0
        # Confirm at least one file really is a readable archive of arrays, so a folder of
        # unrelated .npz blobs doesn't get claimed and then fail mid-scan.
        for candidate in files[:_DETECT_SCAN_LIMIT]:
            try:
                with np.load(candidate, allow_pickle=False) as archive:
                    if archive.files:
                        return 0.7
            except (OSError, ValueError):
                continue
        return 0.0

    def open(self, path: Path, config: ScanConfig) -> DatasetHandle:
        return ArraySourceHandle(
            _NumpyDirSource(path),
            adapter_name=self.name,
            uri=str(path),
            declared=config.schema_map.get("schema", {}) if config.schema_map else {},
            no_vision=config.no_vision,
        )
