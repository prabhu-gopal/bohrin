"""Real MP4 decoding through the LeRobot adapter (docs/03 §3, docs/05 §1, docs/09 §5).

This is the test that would have caught the gap it was written for: the LeRobot adapter
parsed camera *schema* but never decoded the MP4s, so on real LeRobot data every VISION
detector silently had nothing to read. Here we build a genuine LeRobot v2.1 directory with
an actual encoded video and assert the frames come back through the Canonical IR — so a
vision scan on real LeRobot data does real work.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

import bohrin
from bohrin.adapters._video import available as video_available
from bohrin.adapters.registry import select_adapter
from bohrin.config import ScanConfig

pytestmark = pytest.mark.skipif(not video_available(), reason="bohrin[video] (PyAV) not installed")

_LENGTH = 24
_H, _W = 48, 64
_ACTION_DIM = 6
_CAMERA = "observation.images.cam"


def _encode_mp4(path: Path, *, frozen: bool = False) -> None:
    """Encode a real H.264 MP4 — moving frames, or a single frozen frame repeated."""
    import av

    path.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(path), mode="w")
    stream = container.add_stream("libx264", rate=20)
    stream.width, stream.height, stream.pix_fmt = _W, _H, "yuv420p"
    rng = np.random.default_rng(0)
    base = rng.integers(0, 255, size=(_H, _W, 3), dtype=np.uint8)
    for t in range(_LENGTH):
        img = base if frozen else np.roll(base, t, axis=1)
        frame = av.VideoFrame.from_ndarray(np.ascontiguousarray(img), format="rgb24")
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def _build_lerobot_v21(root: Path, *, frozen_video: bool = False) -> Path:
    """A minimal but real LeRobot v2.1 dataset directory with one video camera."""
    (root / "meta").mkdir(parents=True)
    info = {
        "codebase_version": "v2.1",
        "fps": 20,
        "robot_type": "test_arm",
        "chunks_size": 1000,
        "data_path": "data/chunk-{episode_chunk:03d}/episode_{episode_index:06d}.parquet",
        "video_path": "videos/chunk-{episode_chunk:03d}/{video_key}/episode_{episode_index:06d}.mp4",
        "features": {
            "action": {"dtype": "float32", "shape": [_ACTION_DIM]},
            "observation.state": {"dtype": "float32", "shape": [_ACTION_DIM]},
            _CAMERA: {"dtype": "video", "shape": [_H, _W, 3]},
        },
    }
    (root / "meta" / "info.json").write_text(json.dumps(info))
    (root / "meta" / "tasks.jsonl").write_text(json.dumps({"task_index": 0, "task": "pick"}) + "\n")

    n_eps = 10
    lines = []
    for i in range(n_eps):
        lines.append(json.dumps({"episode_index": i, "length": _LENGTH, "tasks": ["pick"]}))
        rng = np.random.default_rng(i)
        action = rng.normal(0.1, 0.3, size=(_LENGTH, _ACTION_DIM)).astype(np.float32)
        df = pl.DataFrame(
            {
                "action": [row.tolist() for row in action],
                "observation.state": [row.tolist() for row in np.cumsum(action, axis=0)],
                "timestamp": (np.arange(_LENGTH) / 20.0).tolist(),
            }
        )
        data_file = root / "data" / "chunk-000" / f"episode_{i:06d}.parquet"
        data_file.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(data_file)
        # Freeze one episode's video so a vision detector has a real defect to find.
        _encode_mp4(root / "videos" / "chunk-000" / _CAMERA / f"episode_{i:06d}.mp4", frozen=frozen_video and i == 3)
    (root / "meta" / "episodes.jsonl").write_text("\n".join(lines) + "\n")
    return root


def test_lerobot_video_frames_reach_the_ir(tmp_path: Path) -> None:
    root = _build_lerobot_v21(tmp_path / "ds")
    adapter = select_adapter(str(root))
    assert adapter.name == "lerobot_v21"

    handle = adapter.open(root, ScanConfig(path=str(root)))
    from bohrin.adapters.base import Sampler

    episode = next(handle.iter_episodes(sample=Sampler()))
    assert _CAMERA in episode.steps.images
    frames = episode.steps.images[_CAMERA]
    assert len(frames) == _LENGTH

    # The decode is real: the frame comes back at the right resolution with 3 channels.
    frame = np.asarray(frames[0].array())
    assert frame.shape == (_H, _W, 3)
    assert frame.max() > frame.min()  # not a black stub — actual pixels decoded


def test_vision_detectors_actually_run_on_lerobot(tmp_path: Path) -> None:
    """The whole point: has_images is True and vision detectors execute on real LeRobot data."""
    root = _build_lerobot_v21(tmp_path / "ds")
    report = bohrin.scan(str(root))
    assert report.dataset.cameras == [_CAMERA]
    assert any(d.startswith("vision.") for d in report.detectors_run), report.detectors_run


def test_frozen_camera_is_caught_on_real_video(tmp_path: Path) -> None:
    """End-to-end: a genuinely frozen MP4 trips vision.frozen_frames through the full pipeline."""
    root = _build_lerobot_v21(tmp_path / "ds", frozen_video=True)
    report = bohrin.scan(str(root))
    assert report.cluster("vision.frozen_frames") is not None


def test_no_vision_flag_skips_decoding(tmp_path: Path) -> None:
    root = _build_lerobot_v21(tmp_path / "ds")
    report = bohrin.scan(str(root), no_vision=True)
    assert not any(d.startswith("vision.") for d in report.detectors_run)


def test_frame_index_is_accurate_not_just_a_nearby_frame(tmp_path: Path) -> None:
    """Decode addresses the *right* frame — the pts→index mapping, not a keyframe-relative count.

    Encodes frames tagged with a known brightness ramp (frame ``t`` is filled with value
    ``10·t``), forces sparse keyframes, then checks a mid-stream frame decodes to its own
    brightness — which a keyframe-relative counter would get wrong.
    """
    import av

    path = tmp_path / "ramp.mp4"
    container = av.open(str(path), mode="w")
    stream = container.add_stream("libx264", rate=20)
    stream.width, stream.height, stream.pix_fmt = 32, 32, "yuv420p"
    stream.options = {"g": "30"}  # a keyframe only every 30 frames
    n = 40
    for t in range(n):
        img = np.full((32, 32, 3), min(10 * t, 250), dtype=np.uint8)
        for packet in stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
            container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()

    from bohrin.adapters._video import VideoFrames

    frames = VideoFrames(path, length=n)
    # Frame 25 sits well past the first keyframe; its mean brightness must match ~10·25.
    mean25 = float(np.asarray(frames[25].array()).mean())
    assert abs(mean25 - 250.0) < 40.0, f"frame 25 decoded to brightness {mean25}, expected ~250"


# ------------------------------------------------------- v3: many episodes packed per MP4

_V3_EPISODES = 5


def _encode_packed_mp4(path: Path, *, n_episodes: int, length: int) -> None:
    """One MP4 holding ``n_episodes`` episodes back to back, each at its own brightness.

    Episode ``e`` is filled with value ``40·(e+1)``, which makes the offset arithmetic
    *observable*: reading a neighbouring episode's frames returns a visibly different
    brightness rather than merely-slightly-wrong pixels.
    """
    import av

    path.parent.mkdir(parents=True, exist_ok=True)
    container = av.open(str(path), mode="w")
    stream = container.add_stream("libx264", rate=20)
    stream.width, stream.height, stream.pix_fmt = _W, _H, "yuv420p"
    stream.options = {"g": "15"}  # sparse keyframes, so offsets must be resolved properly
    for episode in range(n_episodes):
        value = min(40 * (episode + 1), 250)
        for _ in range(length):
            img = np.full((_H, _W, 3), value, dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                container.mux(packet)
    for packet in stream.encode():
        container.mux(packet)
    container.close()


def _build_lerobot_v3(root: Path) -> Path:
    """A minimal but real LeRobot **v3** dataset: many episodes per Parquet *and* per MP4."""
    (root / "meta" / "episodes" / "chunk-000").mkdir(parents=True)
    info = {
        "codebase_version": "v3.0",
        "fps": 20,
        "robot_type": "test_arm",
        "chunks_size": 1000,
        "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
        "features": {
            "action": {"dtype": "float32", "shape": [_ACTION_DIM]},
            "observation.state": {"dtype": "float32", "shape": [_ACTION_DIM]},
            _CAMERA: {"dtype": "video", "shape": [_H, _W, 3]},
        },
    }
    (root / "meta" / "info.json").write_text(json.dumps(info))
    (root / "meta" / "tasks.jsonl").write_text(json.dumps({"task_index": 0, "task": "pick"}) + "\n")

    # One Parquet shard holding every episode's rows, concatenated.
    actions: list[list[float]] = []
    states: list[list[float]] = []
    stamps: list[float] = []
    episode_rows: list[dict[str, object]] = []
    for e in range(_V3_EPISODES):
        rng = np.random.default_rng(e)
        action = rng.normal(0.1, 0.3, size=(_LENGTH, _ACTION_DIM)).astype(np.float32)
        actions.extend(row.tolist() for row in action)
        states.extend(row.tolist() for row in np.cumsum(action, axis=0))
        stamps.extend((np.arange(_LENGTH) / 20.0).tolist())
        episode_rows.append(
            {
                "episode_index": e,
                "length": _LENGTH,
                "tasks": ["pick"],
                "data/chunk_index": 0,
                "data/file_index": 0,
                "dataset_from_index": e * _LENGTH,
                "dataset_to_index": (e + 1) * _LENGTH,
                f"videos/{_CAMERA}/chunk_index": 0,
                f"videos/{_CAMERA}/file_index": 0,
                # The offset is published as a timestamp, in seconds, at the declared fps.
                f"videos/{_CAMERA}/from_timestamp": e * _LENGTH / 20.0,
                f"videos/{_CAMERA}/to_timestamp": (e + 1) * _LENGTH / 20.0,
            }
        )
    data_file = root / "data" / "chunk-000" / "file-000.parquet"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"action": actions, "observation.state": states, "timestamp": stamps}).write_parquet(data_file)
    pl.DataFrame(episode_rows).write_parquet(root / "meta" / "episodes" / "chunk-000" / "file-000.parquet")
    _encode_packed_mp4(
        root / "videos" / _CAMERA / "chunk-000" / "file-000.mp4",
        n_episodes=_V3_EPISODES,
        length=_LENGTH,
    )
    return root


def test_v3_is_detected_and_rows_are_sliced_per_episode(tmp_path: Path) -> None:
    root = _build_lerobot_v3(tmp_path / "ds")
    adapter = select_adapter(str(root))
    assert adapter.name == "lerobot_v3"

    from bohrin.adapters.base import Sampler

    handle = adapter.open(root, ScanConfig(path=str(root)))
    episodes = list(handle.iter_episodes(sample=Sampler()))
    assert len(episodes) == _V3_EPISODES
    # Each episode gets its own rows out of the shared shard, not the whole file.
    assert all(ep.steps.action.shape == (_LENGTH, _ACTION_DIM) for ep in episodes)
    # And the slices are distinct: episode 0 and 3 were generated from different seeds.
    assert not np.allclose(episodes[0].steps.action, episodes[3].steps.action)


def test_v3_packed_video_decodes_the_right_episodes_frames(tmp_path: Path) -> None:
    """The gap this closes: packed video used to be skipped entirely.

    Every episode shares one MP4, so the only thing separating them is the
    ``videos/<key>/from_timestamp`` offset. Each episode is encoded at its own brightness, so
    an off-by-one-episode read is unmissable — which is precisely why the adapter previously
    refused to guess rather than attach the wrong frames.
    """
    root = _build_lerobot_v3(tmp_path / "ds")
    from bohrin.adapters.base import Sampler

    handle = select_adapter(str(root)).open(root, ScanConfig(path=str(root)))
    episodes = list(handle.iter_episodes(sample=Sampler()))

    for e, episode in enumerate(episodes):
        assert _CAMERA in episode.steps.images, f"episode {e} got no video from the packed shard"
        frames = episode.steps.images[_CAMERA]
        assert len(frames) == _LENGTH
        expected = min(40 * (e + 1), 250)
        # Sample a frame from the middle of the episode, away from its boundaries.
        actual = float(np.asarray(frames[_LENGTH // 2].array()).mean())
        assert abs(actual - expected) < 20.0, (
            f"episode {e}: decoded brightness {actual:.0f}, expected ~{expected} — "
            f"the packed-video offset resolved to the wrong episode"
        )


def test_v3_vision_detectors_run_end_to_end(tmp_path: Path) -> None:
    root = _build_lerobot_v3(tmp_path / "ds")
    report = bohrin.scan(str(root))
    assert report.dataset.cameras == [_CAMERA]
    assert any(d.startswith("vision.") for d in report.detectors_run), report.detectors_run


def test_v3_without_declared_fps_refuses_to_guess_the_offset(tmp_path: Path) -> None:
    """No fps ⇒ no timestamp→frame conversion ⇒ attach nothing rather than the wrong frames."""
    root = _build_lerobot_v3(tmp_path / "ds")
    info = json.loads((root / "meta" / "info.json").read_text())
    del info["fps"]
    (root / "meta" / "info.json").write_text(json.dumps(info))

    from bohrin.adapters.base import Sampler

    handle = select_adapter(str(root)).open(root, ScanConfig(path=str(root)))
    episode = next(handle.iter_episodes(sample=Sampler()))
    assert _CAMERA not in episode.steps.images
