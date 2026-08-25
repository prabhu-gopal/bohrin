"""LeRobot adapters — Stage ① for the most common robot-learning format (docs/01 §2.1).

Reads a **local** LeRobotDataset directory (v2.1 one-file-per-episode, or v3 file-based
chunks resolved via ``meta/episodes/*`` offsets) into the Canonical IR. All LeRobot-specific
knowledge is quarantined here: ``info.json`` (schema + path templates), ``stats.json``
(declared normalization), ``tasks`` (labels), and the Parquet tabular data. Detectors never
see any of it.

Reference: LeRobotDataset v3.0 (huggingface.co/docs/lerobot/en/lerobot-dataset-v3).
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from bohrin._arrays import FloatArray
from bohrin.adapters._video import frames_for as video_frames_for
from bohrin.adapters.base import Adapter, DatasetHandle, Sampler
from bohrin.config import ScanConfig
from bohrin.ir.episode import Episode, LazyImage, StepView, TaskLabel
from bohrin.ir.schema import (
    ActionSpace,
    CameraSpec,
    DatasetSchema,
    FeatureStats,
    Provenance,
    SchemaHints,
)

_ACTION_KEY = "action"
_PROPRIO_KEYS = ("observation.state", "observation.proprio")
_TIMESTAMP_KEY = "timestamp"
_VIDEO_DTYPES = frozenset({"video", "image"})
#: v3's default video shard layout, when info.json does not override `video_path`.
_DEFAULT_V3_VIDEO_PATH = "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4"


@dataclass(frozen=True, slots=True)
class _VideoRef:
    """Where one episode's frames live inside a (possibly shared) MP4, for one camera."""

    path: Path
    #: Index of this episode's first frame within ``path``. Non-zero only for packed video.
    start_frame: int
    length: int


@dataclass(frozen=True, slots=True)
class _EpisodeRef:
    """Where one episode's rows live in the (possibly shared) Parquet files."""

    index: int
    length: int
    task: str | None
    data_file: Path
    row_from: int
    row_to: int
    #: Chunk index for resolving this episode's per-camera MP4 path (v2.1 layout).
    chunk: int = 0
    #: Per-camera video location. Empty for v2.1, where the path is derived from the
    #: template instead; populated for v3, where only the metadata knows the offsets.
    videos: Mapping[str, _VideoRef] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Meta:
    root: Path
    version: str
    schema: DatasetSchema
    hints: SchemaHints
    proprio_key: str | None
    episodes: tuple[_EpisodeRef, ...]
    #: The ``video_path`` template from info.json and the camera keys it fills, so the
    #: adapter can resolve each episode's MP4 lazily. ``None`` when the dataset has no video.
    video_template: str | None = None
    camera_keys: tuple[str, ...] = ()


class _LeRobotHandle:
    """An opened LeRobot dataset (either codebase version)."""

    def __init__(self, meta: _Meta, adapter_name: str, *, no_vision: bool = False) -> None:
        self._meta = meta
        self._adapter_name = adapter_name
        self._no_vision = no_vision

    def schema(self) -> DatasetSchema:
        return self._meta.schema

    def profile_hints(self) -> SchemaHints:
        return self._meta.hints

    def episode_count(self) -> int | None:
        return len(self._meta.episodes)

    def iter_episodes(self, *, sample: Sampler) -> Iterator[Episode]:
        """Stream episodes, reading only the rows each one needs (docs/09 §1).

        **Two memory properties this has to have, and previously did not.**

        A v3 shard holds *many* episodes, so ``pl.read_parquet`` on it materializes every
        episode in the file to yield one — and the old per-path cache was unbounded, so a scan
        of a large dataset accumulated every shard it had ever touched. On an OXE-scale mixture
        that is the whole dataset in RAM, which is exactly what the streaming contract exists
        to prevent.

        Instead each episode is read with a lazy ``scan_parquet`` + ``slice``, so Polars pushes
        the row range down and touches only the relevant row groups. Consecutive episodes from
        the same shard are the common case (the refs are sorted by file), so a **single-shard**
        cache keeps that from re-reading the same footer repeatedly while holding at most one
        shard's worth of rows — bounded by construction rather than by hope.
        """
        refs = self._meta.episodes
        keep = set(sample.plan(len(refs)).tolist())
        plan_path: Path | None = None
        plan: pl.LazyFrame | None = None
        for i, ref in enumerate(refs):
            if i not in keep:
                continue
            if plan is None or plan_path != ref.data_file:
                # A LazyFrame is a *query plan*: it parses the footer but holds no rows, so
                # keeping one costs nothing and saves re-reading metadata for the many
                # episodes that share a shard.
                plan_path, plan = ref.data_file, pl.scan_parquet(ref.data_file)
            rows = plan.slice(ref.row_from, ref.row_to - ref.row_from).collect()
            yield self._build_episode(ref, rows)

    def _build_episode(self, ref: _EpisodeRef, rows: pl.DataFrame) -> Episode:
        action = _column_to_2d(rows, _ACTION_KEY)
        proprio = _column_to_2d(rows, self._meta.proprio_key) if self._meta.proprio_key is not None else None
        timestamp = rows[_TIMESTAMP_KEY].to_numpy().astype(np.float64) if _TIMESTAMP_KEY in rows.columns else None
        images = self._episode_videos(ref)
        view = StepView(action=action, proprio=proprio, timestamp=timestamp, images=images)
        source = Provenance(
            adapter=self._adapter_name,
            uri=str(self._meta.root),
            locator=f"{ref.data_file.name} @ episode {ref.index}",
            source_keys={"action": _ACTION_KEY, "proprio": self._meta.proprio_key or ""},
        )
        task = TaskLabel(text=ref.task, task_id=ref.index) if ref.task else None
        return Episode(episode_id=f"episode_{ref.index:06d}", steps=view, source=source, task=task)

    def _episode_videos(self, ref: _EpisodeRef) -> dict[str, Sequence[LazyImage]]:
        """Attach a lazy MP4 handle per camera for this episode (docs/03 §3).

        Two layouts, both decoded:

        * **v2.1 — one MP4 per episode per camera.** The path comes from the ``video_path``
          template and frame ``t`` is data row ``t``.
        * **v3 — many episodes packed into one MP4 per camera shard.** The frame↔row mapping
          is *not* derivable from the file, so it is resolved from ``meta/episodes``:
          ``videos/{key}/chunk_index`` and ``videos/{key}/file_index`` locate the shard, and
          ``videos/{key}/from_timestamp`` gives this episode's offset within it, converted to a
          frame index at the dataset's declared FPS.

        An episode whose offsets are missing is skipped rather than guessed at — reading a
        neighbouring episode's frames would silently attribute one episode's defects to
        another, which is worse than reporting no vision findings for it.
        """
        if self._no_vision:
            return {}
        out: dict[str, Sequence[LazyImage]] = {}
        if ref.videos:  # v3: metadata-resolved, possibly packed
            for key, video in ref.videos.items():
                frames = video_frames_for(video.path, length=video.length, start_frame=video.start_frame)
                if frames is not None:
                    out[key] = frames
            return out
        template = self._meta.video_template
        if template is None or "{episode_index" not in template:
            return {}
        for key in self._meta.camera_keys:
            rel = template.format(episode_chunk=ref.chunk, video_key=key, episode_index=ref.index)
            frames = video_frames_for(self._meta.root / rel, length=ref.length)
            if frames is not None:
                out[key] = frames
        return out


class _LeRobotBase(Adapter):
    """Shared local-directory reader; subclasses pin the codebase version they claim."""

    codebase_prefix = ""

    def detect(self, path: Path) -> float:
        info = path / "meta" / "info.json"
        if not info.is_file():
            return 0.0
        try:
            version = str(_read_json(info).get("codebase_version", ""))
        except (OSError, ValueError):
            return 0.0
        return 1.0 if version.startswith(self.codebase_prefix) else 0.0

    def open(self, path: Path, config: ScanConfig) -> DatasetHandle:
        meta = _load_meta(path)
        return _LeRobotHandle(meta, self.name, no_vision=config.no_vision)


class LeRobotV21Adapter(_LeRobotBase):
    """LeRobotDataset v2.1 — one Parquet/MP4 file per episode."""

    name = "lerobot_v21"
    codebase_prefix = "v2"


class LeRobotV3Adapter(_LeRobotBase):
    """LeRobotDataset v3.0 — many episodes per Parquet/MP4 file, resolved via metadata."""

    name = "lerobot_v3"
    codebase_prefix = "v3"


# --------------------------------------------------------------------------- parsing


def _load_meta(root: Path) -> _Meta:
    info = _read_json(root / "meta" / "info.json")
    version = str(info.get("codebase_version", ""))
    features: dict[str, Any] = info.get("features", {})
    schema, proprio_key = _build_schema(info, features)
    hints = _build_hints(root, info, proprio_key)
    tasks = _load_tasks(root)
    camera_keys = tuple(k for k, feat in features.items() if str(feat.get("dtype")) in _VIDEO_DTYPES)
    episodes = (
        _v21_episodes(root, info, tasks) if version.startswith("v2") else _v3_episodes(root, info, tasks, camera_keys)
    )
    return _Meta(
        root=root,
        version=version,
        schema=schema,
        hints=hints,
        proprio_key=proprio_key,
        episodes=episodes,
        video_template=info.get("video_path") if camera_keys else None,
        camera_keys=camera_keys,
    )


def _build_schema(info: dict[str, Any], features: dict[str, Any]) -> tuple[DatasetSchema, str | None]:
    action_feat = features.get(_ACTION_KEY, {})
    action_dim = _feature_dim(action_feat)
    proprio_key = next((k for k in _PROPRIO_KEYS if k in features), None)
    proprio_dim = _feature_dim(features[proprio_key]) if proprio_key else None
    cameras = tuple(
        _camera_spec(key, feat) for key, feat in features.items() if str(feat.get("dtype")) in _VIDEO_DTYPES
    )
    fps = info.get("fps")
    schema = DatasetSchema(
        action_dim=action_dim,
        action_space=ActionSpace.UNKNOWN,
        action_names=_feature_names(action_feat),
        proprio_dim=proprio_dim,
        proprio_names=_feature_names(features[proprio_key]) if proprio_key else None,
        cameras=cameras,
        control_hz=float(fps) if fps else None,
        embodiment=info.get("robot_type"),
    )
    return schema, proprio_key


def _build_hints(root: Path, info: dict[str, Any], proprio_key: str | None) -> SchemaHints:
    stats_path = root / "meta" / "stats.json"
    if not stats_path.is_file():
        return SchemaHints(declared_fps=float(info["fps"]) if info.get("fps") else None)
    stats = _read_json(stats_path)
    declared: dict[str, FeatureStats] = {}
    for key in (_ACTION_KEY, proprio_key):
        if key and key in stats:
            fs = _feature_stats(stats[key])
            if fs is not None:
                declared[key] = fs
    return SchemaHints(
        declared_stats=declared or None,
        declared_fps=float(info["fps"]) if info.get("fps") else None,
    )


def _v21_episodes(root: Path, info: dict[str, Any], tasks: dict[int, str]) -> tuple[_EpisodeRef, ...]:
    template = info.get("data_path", "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet")
    chunks_size = int(info.get("chunks_size", 1000))
    refs: list[_EpisodeRef] = []
    for row in _read_jsonl(root / "meta" / "episodes.jsonl"):
        idx = int(row["episode_index"])
        length = int(row["length"])
        rel = template.format(episode_chunk=idx // chunks_size, episode_index=idx)
        refs.append(
            _EpisodeRef(
                index=idx,
                length=length,
                task=_first_task(row, tasks),
                data_file=root / rel,
                row_from=0,
                row_to=length,
                chunk=idx // chunks_size,
            )
        )
    return tuple(refs)


def _v3_episodes(
    root: Path,
    info: dict[str, Any],
    tasks: dict[int, str],
    camera_keys: Sequence[str] = (),
) -> tuple[_EpisodeRef, ...]:
    template = info.get("data_path", "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet")
    video_template = info.get("video_path", _DEFAULT_V3_VIDEO_PATH)
    fps = float(info["fps"]) if info.get("fps") else None
    meta_dir = root / "meta" / "episodes"
    # `meta/episodes` is itself chunked (`chunk-*/file-*.parquet`), so recurse rather than
    # globbing one level — a flat glob silently finds nothing on a real v3 dataset.
    frames = [pl.read_parquet(p) for p in sorted(meta_dir.rglob("*.parquet"))]
    if not frames:
        return ()
    table = pl.concat(frames, how="diagonal_relaxed").sort("episode_index")
    rows = list(table.iter_rows(named=True))
    shard_base = _v3_shard_bases(rows)
    refs: list[_EpisodeRef] = []
    for row in rows:
        idx = int(row["episode_index"])
        length = int(row["length"])
        chunk_index = int(row.get("data/chunk_index") or 0)
        file_index = int(row.get("data/file_index") or 0)
        # `dataset_from_index`/`dataset_to_index` count rows across the WHOLE dataset, but the
        # slice below is taken against a single shard, so the global range has to be rebased
        # onto its own file. On a one-shard dataset the base is 0 and this is a no-op, which is
        # why every synthetic fixture passed; on a real multi-shard dataset the first episode of
        # shard N asks for a row past that file's end and comes back empty.
        base = shard_base[(chunk_index, file_index)]
        row_from = int(row.get("dataset_from_index") or 0) - base
        row_to = int(row.get("dataset_to_index") or (row_from + base + length)) - base
        rel = template.format(chunk_index=chunk_index, file_index=file_index)
        refs.append(
            _EpisodeRef(
                index=idx,
                length=length,
                task=_first_task(row, tasks),
                data_file=root / rel,
                row_from=row_from,
                row_to=row_to,
                videos=_v3_videos(root, row, camera_keys, video_template, fps, length),
            )
        )
    return tuple(refs)


def _v3_shard_bases(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[int, int], int]:
    """Map each ``(chunk_index, file_index)`` data shard to its first global row index.

    Taken as the minimum ``dataset_from_index`` over the episodes assigned to that shard, so
    it is read out of the metadata rather than assumed: shards need not be equal-sized, and the
    last one usually is not.
    """
    bases: dict[tuple[int, int], int] = {}
    for row in rows:
        key = (int(row.get("data/chunk_index") or 0), int(row.get("data/file_index") or 0))
        start = int(row.get("dataset_from_index") or 0)
        if key not in bases or start < bases[key]:
            bases[key] = start
    return bases


def _v3_videos(
    root: Path,
    row: Mapping[str, Any],
    camera_keys: Sequence[str],
    template: str,
    fps: float | None,
    length: int,
) -> dict[str, _VideoRef]:
    """Resolve each camera's packed-MP4 location for one v3 episode.

    The offset is published as a **timestamp** (``from_timestamp``), which is converted to a
    frame index at the declared FPS — the only mapping available, since a packed shard carries
    no per-episode marker. Without a declared FPS the conversion would be a guess, so video is
    left unattached instead.
    """
    if not camera_keys:
        return {}
    out: dict[str, _VideoRef] = {}
    for key in camera_keys:
        chunk = row.get(f"videos/{key}/chunk_index")
        file_index = row.get(f"videos/{key}/file_index")
        if chunk is None or file_index is None:
            continue
        rel = template.format(video_key=key, chunk_index=int(chunk), file_index=int(file_index))
        start = row.get(f"videos/{key}/from_timestamp")
        if start is None:
            start_frame = 0  # a single-episode shard: the episode starts at the beginning
        elif fps is None:
            continue  # a packed shard whose offset we cannot convert: refuse to guess
        else:
            start_frame = round(float(start) * fps)
        out[key] = _VideoRef(path=root / rel, start_frame=start_frame, length=length)
    return out


def _load_tasks(root: Path) -> dict[int, str]:
    jsonl = root / "meta" / "tasks.jsonl"
    if jsonl.is_file():
        return {int(r["task_index"]): str(r["task"]) for r in _read_jsonl(jsonl)}
    parquet = root / "meta" / "tasks.parquet"
    if parquet.is_file():
        df = pl.read_parquet(parquet)
        col = "task_index" if "task_index" in df.columns else df.columns[0]
        task_col = "task" if "task" in df.columns else df.columns[-1]
        return {int(i): str(t) for i, t in zip(df[col], df[task_col], strict=False)}
    return {}


# --------------------------------------------------------------------------- helpers


def _feature_dim(feature: dict[str, Any]) -> int:
    shape = feature.get("shape")
    if isinstance(shape, (list, tuple)) and shape:
        return int(shape[0])
    return 0


def _feature_names(feature: dict[str, Any]) -> tuple[str, ...] | None:
    names = feature.get("names")
    if isinstance(names, dict):
        # e.g. {"motors": ["j0", ...]} — take the single list value.
        for value in names.values():
            if isinstance(value, list):
                return tuple(str(n) for n in value)
        return None
    if isinstance(names, list):
        return tuple(str(n) for n in names)
    return None


def _camera_spec(key: str, feature: dict[str, Any]) -> CameraSpec:
    shape = feature.get("shape") or [0, 0, 3]
    h, w = (int(shape[0]), int(shape[1])) if len(shape) >= 2 else (0, 0)
    channels = int(shape[2]) if len(shape) >= 3 else 3
    return CameraSpec(
        key=key,
        height=h,
        width=w,
        channels=channels,
        is_depth=str(feature.get("dtype")) == "depth" or "depth" in key,
    )


def _feature_stats(stat: dict[str, Any]) -> FeatureStats | None:
    try:
        mean = float(np.mean(np.asarray(stat["mean"], dtype=np.float64)))
        std = float(np.mean(np.asarray(stat["std"], dtype=np.float64)))
        lo = float(np.min(np.asarray(stat["min"], dtype=np.float64)))
        hi = float(np.max(np.asarray(stat["max"], dtype=np.float64)))
    except (KeyError, TypeError, ValueError):
        return None
    return FeatureStats(mean=mean, std=std, min=lo, max=hi)


def _first_task(row: dict[str, Any], tasks: dict[int, str]) -> str | None:
    task_field = row.get("tasks")
    if isinstance(task_field, (list, tuple)) and task_field:
        return str(task_field[0])
    if isinstance(task_field, str):
        return task_field
    task_index = row.get("task_index")
    if task_index is not None:
        return tasks.get(int(task_index))
    return None


def _column_to_2d(df: pl.DataFrame, key: str) -> FloatArray:
    """Read a list/array Parquet column into a contiguous ``(T, D)`` float64 array."""
    arr: FloatArray = np.asarray(df[key].to_list(), dtype=np.float64)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    return arr


def _read_json(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out
