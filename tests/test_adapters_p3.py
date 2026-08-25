"""Phase 3 adapters — and the claim they exist to prove (docs/06 P3 DoD).

The headline DoD item is *"the same detectors run unchanged across LeRobot / robomimic /
Zarr / NumPy / custom"*. That is a claim about the **IR**, not about any one adapter, so
the central test here writes one logical dataset — with one planted defect — into several
different on-disk containers and asserts every format yields the same finding.

If the IR were leaky, this test is what would break.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

import bohrin
from bohrin._arrays import AnyArray
from bohrin.adapters._mapping import ArrayInfo, UnmappableDatasetError, infer_mapping
from bohrin.adapters.registry import select_adapter
from bohrin.adapters.zarr_replay import episode_bounds
from bohrin.config import ScanConfig
from bohrin.ir.schema import Severity

h5py = pytest.importorskip("h5py")
zarr = pytest.importorskip("zarr")

_N_EPISODES = 12
_LENGTH = 40
_ACTION_DIM = 6
_DEAD_DIM = 2


def _episode_arrays(index: int) -> tuple[AnyArray, AnyArray, AnyArray]:
    """One clean episode, except action dim 2 is dead — the defect every format must show."""
    rng = np.random.default_rng(1000 + index)
    action = rng.normal(0.0, 0.5, size=(_LENGTH, _ACTION_DIM))
    action[:, _DEAD_DIM] = 0.0  # the planted defect
    proprio = np.cumsum(action, axis=0)
    timestamp = np.arange(_LENGTH, dtype=np.float64) / 20.0
    return action, proprio, timestamp


# --------------------------------------------------------------------------- writers


def write_numpy_dir(root: Path) -> Path:
    out = root / "npz_dataset"
    out.mkdir()
    for i in range(_N_EPISODES):
        action, proprio, timestamp = _episode_arrays(i)
        np.savez(out / f"episode_{i:03d}.npz", action=action, state=proprio, timestamp=timestamp)
    return out


def write_robomimic(root: Path) -> Path:
    out = root / "robomimic.hdf5"
    with h5py.File(out, "w") as f:
        data = f.create_group("data")
        for i in range(_N_EPISODES):
            action, proprio, timestamp = _episode_arrays(i)
            demo = data.create_group(f"demo_{i}")
            demo.create_dataset("actions", data=action)
            demo.create_dataset("states", data=proprio)
            demo.create_dataset("timestamp", data=timestamp)
        mask = f.create_group("mask")
        mask.create_dataset("train", data=np.array([f"demo_{i}".encode() for i in range(8)]))
        mask.create_dataset("valid", data=np.array([f"demo_{i}".encode() for i in range(8, _N_EPISODES)]))
    return out


def _zarr_write(group: Any, name: str, data: AnyArray) -> None:
    """Write an array through whichever API this Zarr major version exposes.

    zarr 2 has ``create_dataset(name, data=...)``; zarr 3 replaced it with
    ``create_array(name, shape=, dtype=)``. Supporting both keeps the test honest about
    what a user's environment might actually have installed.
    """
    creator = getattr(group, "create_array", None) or group.create_dataset
    try:
        creator(name, data=data)
    except TypeError:  # zarr 3 wants shape/dtype up front
        arr = creator(name, shape=data.shape, dtype=data.dtype)
        arr[:] = data


def write_zarr(root: Path) -> Path:
    out = root / "replay.zarr"
    actions, proprios, stamps, ends = [], [], [], []
    total = 0
    for i in range(_N_EPISODES):
        action, proprio, timestamp = _episode_arrays(i)
        actions.append(action)
        proprios.append(proprio)
        stamps.append(timestamp)
        total += _LENGTH
        ends.append(total)
    store = zarr.open(str(out), mode="w")
    data = store.create_group("data")
    _zarr_write(data, "action", np.concatenate(actions))
    _zarr_write(data, "state", np.concatenate(proprios))
    _zarr_write(data, "timestamp", np.concatenate(stamps))
    meta = store.create_group("meta")
    _zarr_write(meta, "episode_ends", np.asarray(ends, dtype=np.int64))
    return out


_WRITERS = {
    "numpy_dir": write_numpy_dir,
    "robomimic_hdf5": write_robomimic,
    "zarr_replaybuffer": write_zarr,
}


# ------------------------------------------------------- the DoD: one IR, many containers


@pytest.mark.parametrize("fmt", sorted(_WRITERS))
def test_format_is_autodetected(fmt: str, tmp_path: Path) -> None:
    path = _WRITERS[fmt](tmp_path)
    assert select_adapter(str(path)).name == fmt


@pytest.mark.parametrize("fmt", sorted(_WRITERS))
def test_same_detector_fires_on_every_container(fmt: str, tmp_path: Path) -> None:
    """docs/06 P3 DoD: detectors run unchanged across formats — the IR is the contract."""
    path = _WRITERS[fmt](tmp_path)
    report = bohrin.scan(str(path))

    assert report.dataset.format == fmt
    assert report.dataset.n_episodes == _N_EPISODES
    assert report.dataset.action_dim == _ACTION_DIM

    cluster = report.cluster("stats.dead_dimension")
    assert cluster is not None, f"{fmt}: the planted dead dimension was not found"
    assert cluster.severity is Severity.HIGH
    assert cluster.findings[0].locus.dimensions == [_DEAD_DIM]


def test_all_containers_agree_on_the_finding(tmp_path: Path) -> None:
    """The strongest form of the claim: identical findings, not merely 'each one fires'."""
    seen: dict[str, tuple[int, ...]] = {}
    for fmt, writer in sorted(_WRITERS.items()):
        root = tmp_path / fmt
        root.mkdir()
        report = bohrin.scan(str(writer(root)))
        cluster = report.cluster("stats.dead_dimension")
        assert cluster is not None
        seen[fmt] = tuple(cluster.findings[0].locus.dimensions)
    assert len(set(seen.values())) == 1, f"formats disagree about the defect: {seen}"


# --------------------------------------------------------------------- the schema mapper


def test_mapper_prefers_declared_over_inferred() -> None:
    arrays = [ArrayInfo("action", (10, 6)), ArrayInfo("weird_column", (10, 7))]
    mapping = infer_mapping(arrays, {"action": "weird_column"})
    assert mapping.action == "weird_column"


def test_mapper_resolves_nested_paths() -> None:
    arrays = [
        ArrayInfo("data/demo_0/actions", (10, 6)),
        ArrayInfo("data/demo_0/obs/state", (10, 7)),
        ArrayInfo("data/demo_0/obs/agentview_image", (10, 84, 84, 3)),
    ]
    mapping = infer_mapping(arrays)
    assert mapping.action == "data/demo_0/actions"
    assert mapping.proprio == "data/demo_0/obs/state"
    assert mapping.images == ("data/demo_0/obs/agentview_image",)


def test_mapper_separates_depth_from_rgb() -> None:
    arrays = [
        ArrayInfo("action", (10, 6)),
        ArrayInfo("rgb_image", (10, 64, 64, 3)),
        ArrayInfo("depth_image", (10, 64, 64)),
    ]
    mapping = infer_mapping(arrays)
    assert mapping.images == ("rgb_image",)
    assert mapping.depth == ("depth_image",)


def test_mapper_refuses_rather_than_guessing_when_nothing_matches() -> None:
    """A wrong action column yields confident nonsense — erroring is the honest outcome."""
    arrays = [ArrayInfo("mystery", (10, 64, 64, 3))]
    with pytest.raises(UnmappableDatasetError, match="bohrin init"):
        infer_mapping(arrays, allow_shape_fallback=False)


def test_mapper_never_claims_an_image_as_the_action() -> None:
    arrays = [ArrayInfo("camera_top", (10, 64, 64, 3)), ArrayInfo("motor_cmd", (10, 7))]
    assert infer_mapping(arrays).action == "motor_cmd"


# ------------------------------------------------------------- zarr boundary arithmetic


def test_episode_bounds_converts_ends_to_slices() -> None:
    assert episode_bounds([3, 7, 10]) == [(0, 3), (3, 7), (7, 10)]


def test_episode_bounds_skips_empty_episodes() -> None:
    """A repeated offset means a zero-length episode; emitting it would break the IR."""
    assert episode_bounds([3, 3, 8]) == [(0, 3), (3, 8)]


# ----------------------------------------------------------------------- raw/custom HDF5


def test_raw_hdf5_reads_a_flat_custom_file(tmp_path: Path) -> None:
    out = tmp_path / "custom.h5"
    with h5py.File(out, "w") as f:
        for i in range(_N_EPISODES):
            action, proprio, _ = _episode_arrays(i)
            g = f.create_group(f"traj{i}")
            g.create_dataset("action", data=action)
            g.create_dataset("qpos", data=proprio)
    adapter = select_adapter(str(out))
    assert adapter.name == "raw_hdf5"  # robomimic must not claim a non-robomimic file
    report = bohrin.scan(str(out))
    assert report.dataset.n_episodes == _N_EPISODES
    assert report.cluster("stats.dead_dimension") is not None


def test_episodes_are_ordered_naturally_not_lexically(tmp_path: Path) -> None:
    """demo_10 must not sort between demo_1 and demo_2 — findings cite episode ids."""
    out = tmp_path / "many.hdf5"
    with h5py.File(out, "w") as f:
        data = f.create_group("data")
        for i in range(12):
            action, _, _ = _episode_arrays(i)
            data.create_group(f"demo_{i}").create_dataset("actions", data=action)
    adapter = select_adapter(str(out))
    handle = adapter.open(out, _config(str(out)))
    from bohrin.adapters.base import Sampler

    ids = [ep.episode_id for ep in handle.iter_episodes(sample=Sampler())]
    assert ids == [f"demo_{i}" for i in range(12)]


def _config(path: str) -> ScanConfig:
    return ScanConfig(path=path)
