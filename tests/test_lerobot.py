"""LeRobot adapter over a synthetic on-disk dataset (docs/06 P1 DoD — real format, no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

import bohrin
from bohrin._arrays import FloatArray
from bohrin.adapters.base import Sampler
from bohrin.adapters.lerobot import LeRobotV3Adapter, LeRobotV21Adapter
from bohrin.config import ScanConfig

_NAMES = ["x", "y", "z", "roll", "pitch", "grip"]


def _episode_arrays(
    index: int, length: int, action_dim: int, dead_dim: int | None
) -> tuple[FloatArray, FloatArray, FloatArray]:
    rng = np.random.default_rng(index)
    deltas = rng.normal(0.0, 0.02, size=(length, action_dim))
    if dead_dim is not None:
        deltas[:, dead_dim] = 0.0
    state = np.zeros_like(deltas)
    state[1:] = np.cumsum(deltas[:-1], axis=0)  # causally-aligned proprio (no false lag)
    ts = np.arange(length, dtype=np.float64) / 20.0
    return deltas, state, ts


def _features(action_dim: int) -> dict[str, Any]:
    names = _NAMES[:action_dim]
    return {
        "action": {"dtype": "float32", "shape": [action_dim], "names": names},
        "observation.state": {"dtype": "float32", "shape": [action_dim], "names": names},
        "observation.images.front": {"dtype": "video", "shape": [480, 640, 3], "names": None},
        "timestamp": {"dtype": "float32", "shape": [1], "names": None},
    }


def _write_stats(meta: Path, action: FloatArray, state: FloatArray) -> None:
    def block(a: FloatArray) -> dict[str, Any]:
        return {
            "mean": a.mean(0).tolist(),
            "std": a.std(0).tolist(),
            "min": a.min(0).tolist(),
            "max": a.max(0).tolist(),
        }

    (meta / "stats.json").write_text(json.dumps({"action": block(action), "observation.state": block(state)}))


def write_v21(root: Path, *, n_episodes: int = 6, length: int = 30, dead_dim: int | None = None) -> None:
    action_dim = 6
    meta = root / "meta"
    meta.mkdir(parents=True)
    (root / "data" / "chunk-000").mkdir(parents=True)
    info = {
        "codebase_version": "v2.1",
        "robot_type": "so101",
        "fps": 20,
        "chunks_size": 1000,
        "data_path": "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
        "features": _features(action_dim),
        "total_episodes": n_episodes,
    }
    (meta / "info.json").write_text(json.dumps(info))
    all_action, all_state = [], []
    ep_lines = []
    for i in range(n_episodes):
        deltas, state, ts = _episode_arrays(i, length, action_dim, dead_dim)
        pl.DataFrame(
            {
                "action": [r.tolist() for r in deltas],
                "observation.state": [r.tolist() for r in state],
                "timestamp": ts,
            }
        ).write_parquet(root / f"data/chunk-000/episode_{i:06d}.parquet")
        all_action.append(deltas)
        all_state.append(state)
        ep_lines.append({"episode_index": i, "tasks": ["pick the cube"], "length": length})
    _write_stats(meta, np.vstack(all_action), np.vstack(all_state))
    (meta / "tasks.jsonl").write_text(json.dumps({"task_index": 0, "task": "pick the cube"}) + "\n")
    (meta / "episodes.jsonl").write_text("\n".join(json.dumps(line) for line in ep_lines))


def write_v3(root: Path, *, n_episodes: int = 6, length: int = 30, episodes_per_shard: int = 0) -> None:
    """Write a LeRobot v3 dataset.

    ``episodes_per_shard`` splits ``data/`` across several ``file-NNN.parquet`` shards, as every
    real v3 dataset above a size threshold does. The default of 0 keeps everything in one shard.
    """
    action_dim = 6
    per_shard = episodes_per_shard or n_episodes
    meta = root / "meta"
    (meta / "episodes").mkdir(parents=True)
    (root / "data" / "chunk-000").mkdir(parents=True)
    info = {
        "codebase_version": "v3.0",
        "robot_type": "aloha",
        "fps": 20,
        "chunks_size": 1000,
        "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        "features": _features(action_dim),
        "total_episodes": n_episodes,
    }
    (meta / "info.json").write_text(json.dumps(info))
    all_actions: list[list[float]] = []
    all_states: list[list[float]] = []
    shards: dict[int, dict[str, list[Any]]] = {}
    ep_meta: list[dict[str, Any]] = []
    cursor = 0
    for i in range(n_episodes):
        deltas, state, ts = _episode_arrays(i, length, action_dim, None)
        shard = i // per_shard
        bucket = shards.setdefault(shard, {"action": [], "observation.state": [], "timestamp": []})
        bucket["action"].extend(r.tolist() for r in deltas)
        bucket["observation.state"].extend(r.tolist() for r in state)
        bucket["timestamp"].extend(ts.tolist())
        all_actions.extend(r.tolist() for r in deltas)
        all_states.extend(r.tolist() for r in state)
        ep_meta.append(
            {
                "episode_index": i,
                "length": length,
                "tasks": ["fold the towel"],
                "data/chunk_index": 0,
                "data/file_index": shard,
                # Global row indices, exactly as real v3 metadata records them — they keep
                # counting across shard boundaries rather than restarting per file.
                "dataset_from_index": cursor,
                "dataset_to_index": cursor + length,
            }
        )
        cursor += length
    for shard, bucket in shards.items():
        pl.DataFrame(bucket).write_parquet(root / f"data/chunk-000/file-{shard:03d}.parquet")
    pl.DataFrame(ep_meta).write_parquet(meta / "episodes" / "episodes-000.parquet")
    _write_stats(meta, np.array([a for a in all_actions]), np.array([s for s in all_states]))


def test_v21_detects_and_scans(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    write_v21(root)
    assert LeRobotV21Adapter().detect(root) == 1.0
    assert LeRobotV3Adapter().detect(root) == 0.0

    report = bohrin.scan(str(root))
    assert report.dataset.format == "lerobot_v21"
    assert report.dataset.n_episodes == 6
    assert report.dataset.embodiment == "so101"
    assert report.dataset.action_dim == 6
    assert report.dataset.control_hz == 20.0
    assert any("front" in cam for cam in report.dataset.cameras)


def test_v21_finds_injected_dead_dimension(tmp_path: Path) -> None:
    root = tmp_path / "ds"
    write_v21(root, dead_dim=3)
    report = bohrin.scan(str(root))
    cluster = report.cluster("stats.dead_dimension")
    assert cluster is not None
    assert 3 in cluster.findings[0].locus.dimensions


def test_init_writes_bohrin_yaml(tmp_path: Path) -> None:
    import yaml

    from bohrin.cli import main

    root = tmp_path / "ds"
    write_v21(root)
    assert main(["init", str(root)]) == 0
    doc = yaml.safe_load((root / "bohrin.yaml").read_text())
    assert doc["format"] == "lerobot_v21"
    assert doc["action_dim"] == 6
    assert doc["control_hz"] == 20.0


def test_v3_detects_and_scans(tmp_path: Path) -> None:
    root = tmp_path / "ds3"
    write_v3(root)
    assert LeRobotV3Adapter().detect(root) == 1.0
    assert LeRobotV21Adapter().detect(root) == 0.0

    report = bohrin.scan(str(root))
    assert report.dataset.format == "lerobot_v3"
    assert report.dataset.n_episodes == 6
    assert report.dataset.embodiment == "aloha"


def test_v3_reads_every_episode_when_data_is_split_across_shards(tmp_path: Path) -> None:
    """Regression: v3 row indices are dataset-global, but each slice is taken from one shard.

    Found on ``lerobot/aloha_sim_transfer_cube_human`` (3 shards), which crashed outright with
    ``episode 'episode_000023' has no steps`` — episode 23 is the first of shard 1, so its global
    ``dataset_from_index`` of 9200 pointed one row past the end of its own 9200-row file. Every
    fixture until now used a single shard, where the rebase is a no-op and the bug is invisible.
    """
    root = tmp_path / "sharded"
    write_v3(root, n_episodes=9, length=10, episodes_per_shard=4)
    assert len(sorted((root / "data" / "chunk-000").glob("*.parquet"))) == 3, "fixture is not sharded"

    report = bohrin.scan(str(root), full=True)
    assert report.dataset.n_episodes == 9


def test_v3_shard_rebasing_returns_the_correct_rows_not_merely_some_rows(tmp_path: Path) -> None:
    """A wrong-but-nonempty slice would pass the crash test while silently mixing up episodes."""
    root = tmp_path / "sharded"
    write_v3(root, n_episodes=9, length=10, episodes_per_shard=4)
    handle = LeRobotV3Adapter().open(root, ScanConfig(path=str(root), no_vision=True))

    # An uncapped Sampler keeps every episode — exactly what this test needs, and it is the
    # real type the adapter is contracted against rather than a look-alike.
    read = {ep.episode_id: ep.steps.action for ep in handle.iter_episodes(sample=Sampler())}
    assert len(read) == 9
    for index in range(9):
        shard = index // 4
        offset = (index % 4) * 10
        truth = np.array(pl.read_parquet(root / f"data/chunk-000/file-{shard:03d}.parquet")["action"].to_list())[
            offset : offset + 10
        ]
        got = read[f"episode_{index:06d}"]
        assert np.array_equal(got, truth), f"episode {index} (shard {shard}) read the wrong rows"
