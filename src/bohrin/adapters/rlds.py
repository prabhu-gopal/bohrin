"""RLDS / TFDS adapter — the Open X-Embodiment format (docs/01 §2.2, docs/06 P3).

RLDS stores a dataset as a TFDS builder directory: ``dataset_info.json`` + ``features.json``
describing a nested feature dict, and TFRecord shards holding episodes, each of which is a
dict with a ``steps`` sub-dataset. This is how Open X-Embodiment, RT-1, Bridge and most
Google-origin robot datasets ship.

Two things make this adapter different from the array-container ones:

* **The schema is declared.** ``features.json`` names every observation and its shape, so
  the mapper is a fallback here, not the primary mechanism.
* **Steps are a nested dataset, not an array.** One episode must be materialized step by
  step, so we convert to NumPy per episode and never hold more than one at a time.

TensorFlow is a heavy optional dependency (``bohrin[rlds]``), imported lazily so that a
LeRobot-only user never pays for it — importing TF costs seconds and allocates GPU memory.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from bohrin._arrays import AnyArray
from bohrin.adapters._arraysource import _as_1d, _as_2d, _ImageFrames
from bohrin.adapters._mapping import ArrayInfo, infer_mapping
from bohrin.adapters.base import Adapter, DatasetHandle, Sampler
from bohrin.config import ScanConfig
from bohrin.ir.episode import Episode, StepView, TaskLabel
from bohrin.ir.schema import ActionSpace, CameraSpec, DatasetSchema, Provenance, SchemaHints

_FEATURES_FILE = "features.json"
_INFO_FILE = "dataset_info.json"
_STEPS_KEY = "steps"
_LANGUAGE_KEYS = ("language_instruction", "natural_language_instruction", "instruction")


def _tfds() -> Any:
    try:
        import tensorflow_datasets as tfds
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "reading RLDS/TFDS datasets requires the optional dependency: pip install 'bohrin[rlds]'"
        ) from exc
    return tfds


def _available() -> bool:
    try:
        import tensorflow_datasets  # noqa: F401
    except ImportError:  # pragma: no cover - depends on the install
        return False
    return True


def flatten_step(step: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten one RLDS step's nested dict into ``observation/image``-style keys.

    Pure and dependency-free so the flattening rule — the part that decides what the
    mapper even sees — is testable without TensorFlow installed.
    """
    out: dict[str, Any] = {}
    for key, value in step.items():
        path = f"{prefix}/{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            out.update(flatten_step(value, path))
        else:
            out[path] = value
    return out


def _decode(value: Any) -> Any:
    """Convert a TF tensor / bytes to NumPy or ``str``; pass anything else through."""
    if hasattr(value, "numpy"):
        value = value.numpy()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class _RldsHandle:
    """An opened TFDS builder directory."""

    def __init__(self, path: Path, config: ScanConfig, adapter_name: str) -> None:
        self._path = path
        self._config = config
        self._adapter_name = adapter_name
        tfds = _tfds()
        self._builder = tfds.builder_from_directory(str(path))
        self._split = next(iter(self._builder.info.splits))
        self._n_episodes = int(self._builder.info.splits[self._split].num_examples)

        first = self._first_episode_arrays()
        infos = [ArrayInfo(key=k, shape=tuple(int(d) for d in np.asarray(v).shape)) for k, v in first.items()]
        declared = config.schema_map.get("schema", {}) if config.schema_map else {}
        self._mapping = infer_mapping(infos, declared)
        self._schema = self._build_schema(first)

    def _first_episode_arrays(self) -> dict[str, AnyArray]:
        for arrays, _ in self._iter_raw(limit=1):
            return arrays
        raise ValueError(f"rlds: no episodes found in {self._path}")

    def _build_schema(self, sample: Mapping[str, AnyArray]) -> DatasetSchema:
        m = self._mapping
        action = _as_2d(sample[m.action])
        proprio = _as_2d(sample[m.proprio]) if m.proprio and m.proprio in sample else None
        cameras = tuple(
            CameraSpec(key=k, height=int(sample[k].shape[1]), width=int(sample[k].shape[2]))
            for k in m.images
            if k in sample and np.asarray(sample[k]).ndim >= 3
        )
        return DatasetSchema(
            action_dim=int(action.shape[1]),
            action_space=ActionSpace.UNKNOWN,
            proprio_dim=None if proprio is None else int(proprio.shape[1]),
            cameras=cameras,
            control_hz=None,  # RLDS rarely declares a rate; measuring it would be a guess
            embodiment=self._builder.info.name,
        )

    def _iter_raw(self, *, limit: int | None = None) -> Iterator[tuple[dict[str, AnyArray], str | None]]:
        """Yield ``(flattened columnar arrays, task)`` one episode at a time."""
        dataset = self._builder.as_dataset(split=self._split)
        for count, episode in enumerate(dataset):
            if limit is not None and count >= limit:
                return
            columns: dict[str, list[Any]] = {}
            task: str | None = None
            for step in episode[_STEPS_KEY]:
                # Flatten *first*, then decode each leaf. Decoding the top level first left
                # every nested value untouched, which silently defeated two things: the
                # language-instruction lookup below matches on a key *suffix* precisely so it
                # can find `observation/natural_language_instruction` (where much of Open-X
                # puts it), but a nested instruction arrived as undecoded bytes and never
                # matched the `str` test — so those datasets scanned as unlabelled. Nested
                # numeric tensors only worked at all because TensorFlow's eager tensors happen
                # to implement `__array__`; relying on that made the adapter's real contract
                # with TFDS untestable without TensorFlow installed.
                flat = {key: _decode(value) for key, value in flatten_step(step).items()}
                for key, value in flat.items():
                    if isinstance(value, str):
                        if task is None and any(key.endswith(lk) for lk in _LANGUAGE_KEYS):
                            task = value
                        continue
                    columns.setdefault(key, []).append(value)
            yield {k: np.asarray(v) for k, v in columns.items()}, task

    def schema(self) -> DatasetSchema:
        return self._schema

    def profile_hints(self) -> SchemaHints:
        return SchemaHints.empty()

    def episode_count(self) -> int | None:
        return self._n_episodes

    def iter_episodes(self, *, sample: Sampler) -> Iterator[Episode]:
        keep = set(sample.plan(self._n_episodes).tolist())
        m = self._mapping
        for index, (arrays, task) in enumerate(self._iter_raw()):
            if index not in keep:
                continue
            action = _as_2d(arrays[m.action])
            images: dict[str, Sequence[_ImageFrames]] = {}
            if not self._config.no_vision:
                for cam in m.images:
                    if cam in arrays:
                        images[cam] = [_ImageFrames(arrays[cam], t) for t in range(len(arrays[cam]))]
            steps = StepView(
                action=action,
                timestamp=_as_1d(arrays[m.timestamp]) if m.timestamp and m.timestamp in arrays else None,
                proprio=_as_2d(arrays[m.proprio]) if m.proprio and m.proprio in arrays else None,
                reward=_as_1d(arrays[m.reward]) if m.reward and m.reward in arrays else None,
                images=images,
            )
            yield Episode(
                episode_id=f"episode_{index:05d}",
                steps=steps,
                source=Provenance(
                    adapter=self._adapter_name,
                    uri=str(self._path),
                    locator=f"{self._split}[{index}]",
                ),
                task=None if task is None else TaskLabel(text=task),
            )


class RldsAdapter(Adapter):
    """RLDS / TFDS builder directory (Open X-Embodiment and friends)."""

    name = "rlds"

    def detect(self, path: Path) -> float:
        """Detect from files alone, so an uninstalled TensorFlow still gives a clear error.

        We deliberately claim the path even when ``bohrin[rlds]`` is missing: the layout is
        unambiguous, and "install this extra" is far more useful than "unknown format".
        """
        if not path.is_dir():
            return 0.0
        if not (path / _FEATURES_FILE).is_file():
            return 0.0
        try:
            features = json.loads((path / _FEATURES_FILE).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0.0
        # An RLDS features tree always has a `steps` sequence at the top level.
        blob = json.dumps(features)
        if _STEPS_KEY not in blob:
            return 0.0
        return 0.95 if (path / _INFO_FILE).is_file() else 0.7

    def open(self, path: Path, config: ScanConfig) -> DatasetHandle:
        if not _available():
            raise ImportError("this looks like an RLDS/TFDS dataset; reading it requires: pip install 'bohrin[rlds]'")
        return _RldsHandle(path, config, self.name)


__all__ = ["RldsAdapter", "flatten_step"]
