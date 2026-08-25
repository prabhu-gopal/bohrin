"""The RLDS/TFDS reader, exercised without TensorFlow (docs/01 §2.2).

RLDS is the Open X-Embodiment format — the one most likely to meet real-world data — and it
was the least-covered module in the package (40 %), because every path past ``detect()``
needs ``tensorflow_datasets`` and CI does not install a gigabyte of TensorFlow to check a
flattening rule.

The fix is a **stub builder** injected into ``sys.modules``: the adapter's own contract with
TFDS is small and explicit (``builder_from_directory`` → ``info.splits`` → ``as_dataset`` →
episodes containing a ``steps`` sub-dataset), so it can be honoured faithfully in a few dozen
lines. What that buys is coverage of the parts that actually break on real data — the nested
flattening, the tensor/bytes decoding, language-instruction discovery, schema inference, and
the streaming/sampling path — none of which depend on TensorFlow's behaviour, only on its shape.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from bohrin.adapters.base import Sampler
from bohrin.adapters.rlds import RldsAdapter, flatten_step
from bohrin.config import ScanConfig

_LENGTH = 12
_ACTION_DIM = 7
_IMAGE = (16, 20, 3)


class _Tensor:
    """A value that must be unwrapped via ``.numpy()``, the way a TF eager tensor is."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def numpy(self) -> Any:
        return self._value


def _episode_steps(index: int, *, with_image: bool, instruction: str | None) -> list[dict[str, Any]]:
    """One episode's steps, nested exactly as RLDS nests them."""
    rng = np.random.default_rng(index)
    steps: list[dict[str, Any]] = []
    for t in range(_LENGTH):
        observation: dict[str, Any] = {
            "state": _Tensor(rng.normal(size=_ACTION_DIM).astype(np.float32)),
        }
        if with_image:
            observation["image"] = _Tensor(rng.integers(0, 255, size=_IMAGE).astype(np.uint8))
        step: dict[str, Any] = {
            "action": _Tensor(rng.normal(size=_ACTION_DIM).astype(np.float32)),
            "observation": observation,
            "reward": _Tensor(np.float32(t * 0.1)),
            "is_terminal": _Tensor(np.bool_(t == _LENGTH - 1)),
        }
        if instruction is not None:
            # Bytes, as TFDS yields strings — the adapter has to decode them.
            step["language_instruction"] = _Tensor(instruction.encode("utf-8"))
        steps.append(step)
    return steps


def _nested_instruction_steps(instruction: str) -> list[dict[str, Any]]:
    """Steps whose instruction lives under ``observation/`` — the Open-X placement."""
    rng = np.random.default_rng(0)
    return [
        {
            "action": _Tensor(rng.normal(size=_ACTION_DIM).astype(np.float32)),
            "observation": {
                "state": _Tensor(rng.normal(size=_ACTION_DIM).astype(np.float32)),
                "natural_language_instruction": _Tensor(instruction.encode("utf-8")),
            },
        }
        for _ in range(_LENGTH)
    ]


class _NestedInstructionBuilder:
    def __init__(self, n_episodes: int, instruction: str) -> None:
        self._n = n_episodes
        self._instruction = instruction
        self.info = _StubInfo(n_episodes, "nested_dataset")

    def as_dataset(self, split: str) -> Iterator[dict[str, Any]]:
        for _ in range(self._n):
            yield {"steps": _nested_instruction_steps(self._instruction)}


class _StubBuilder:
    def __init__(self, n_episodes: int, *, with_image: bool, instruction: str | None, name: str) -> None:
        self._n = n_episodes
        self._with_image = with_image
        self._instruction = instruction
        self.info = _StubInfo(n_episodes, name)

    def as_dataset(self, split: str) -> Iterator[dict[str, Any]]:
        assert split == "train"
        for i in range(self._n):
            yield {"steps": _episode_steps(i, with_image=self._with_image, instruction=self._instruction)}


class _StubSplit:
    def __init__(self, num_examples: int) -> None:
        self.num_examples = num_examples


class _StubInfo:
    def __init__(self, n_episodes: int, name: str) -> None:
        self.splits = {"train": _StubSplit(n_episodes)}
        self.name = name


@pytest.fixture
def rlds_root(tmp_path: Path) -> Path:
    """A directory the adapter's file-only ``detect()`` accepts as RLDS."""
    root = tmp_path / "openx_like"
    root.mkdir()
    (root / "features.json").write_text(json.dumps({"steps": {"action": {}, "observation": {}}}))
    (root / "dataset_info.json").write_text(json.dumps({"name": "stub_dataset"}))
    return root


def _install_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    n_episodes: int = 6,
    with_image: bool = True,
    instruction: str | None = "pick up the cube",
    name: str = "stub_dataset",
) -> None:
    """Inject a fake ``tensorflow_datasets`` satisfying the adapter's contract."""
    module = type(sys)("tensorflow_datasets")
    module.builder_from_directory = lambda path: _StubBuilder(  # type: ignore[attr-defined]
        n_episodes, with_image=with_image, instruction=instruction, name=name
    )
    monkeypatch.setitem(sys.modules, "tensorflow_datasets", module)


# ------------------------------------------------------------------- the flattening rule


def test_flatten_step_builds_slash_separated_keys() -> None:
    flat = flatten_step({"action": 1, "observation": {"image": 2, "nested": {"deep": 3}}})
    assert flat == {"action": 1, "observation/image": 2, "observation/nested/deep": 3}


def test_flatten_step_is_empty_for_an_empty_step() -> None:
    assert flatten_step({}) == {}


# ------------------------------------------------------------------------ opening a dataset


def test_open_infers_a_schema_from_the_first_episode(rlds_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub(monkeypatch)
    handle = RldsAdapter().open(rlds_root, ScanConfig(path=str(rlds_root)))
    schema = handle.schema()
    assert schema.action_dim == _ACTION_DIM
    assert schema.proprio_dim == _ACTION_DIM
    assert [c.key for c in schema.cameras] == ["observation/image"]
    assert schema.cameras[0].height == _IMAGE[0]
    assert schema.cameras[0].width == _IMAGE[1]
    # RLDS rarely declares a control rate; guessing one would be a fabricated fact.
    assert schema.control_hz is None
    assert schema.embodiment == "stub_dataset"


def test_episode_count_comes_from_the_split_metadata(rlds_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub(monkeypatch, n_episodes=9)
    handle = RldsAdapter().open(rlds_root, ScanConfig(path=str(rlds_root)))
    assert handle.episode_count() == 9


def test_episodes_reach_the_canonical_ir(rlds_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub(monkeypatch, n_episodes=4)
    handle = RldsAdapter().open(rlds_root, ScanConfig(path=str(rlds_root)))
    episodes = list(handle.iter_episodes(sample=Sampler()))

    assert len(episodes) == 4
    first = episodes[0]
    assert first.steps.action.shape == (_LENGTH, _ACTION_DIM)
    assert first.steps.proprio is not None
    assert first.steps.proprio.shape == (_LENGTH, _ACTION_DIM)
    assert first.steps.reward is not None
    # The bytes instruction was decoded to text, not left as a repr.
    assert first.task is not None
    assert first.task.text == "pick up the cube"
    assert first.source.adapter == "rlds"
    assert "train[0]" in first.source.locator


def test_images_arrive_as_lazy_frames(rlds_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub(monkeypatch, n_episodes=2)
    handle = RldsAdapter().open(rlds_root, ScanConfig(path=str(rlds_root)))
    episode = next(handle.iter_episodes(sample=Sampler()))
    assert "observation/image" in episode.steps.images
    frames = episode.steps.images["observation/image"]
    assert len(frames) == _LENGTH
    assert np.asarray(frames[0].array()).shape == _IMAGE


def test_no_vision_skips_image_columns(rlds_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub(monkeypatch, n_episodes=2)
    handle = RldsAdapter().open(rlds_root, ScanConfig(path=str(rlds_root), no_vision=True))
    episode = next(handle.iter_episodes(sample=Sampler()))
    assert episode.steps.images == {}


def test_a_proprio_only_dataset_opens(rlds_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub(monkeypatch, n_episodes=3, with_image=False)
    handle = RldsAdapter().open(rlds_root, ScanConfig(path=str(rlds_root)))
    assert handle.schema().cameras == ()
    assert next(handle.iter_episodes(sample=Sampler())).steps.images == {}


def test_an_unlabelled_dataset_yields_no_task(rlds_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub(monkeypatch, n_episodes=2, instruction=None)
    handle = RldsAdapter().open(rlds_root, ScanConfig(path=str(rlds_root)))
    assert next(handle.iter_episodes(sample=Sampler())).task is None


def test_sampling_selects_a_subset_deterministically(rlds_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub(monkeypatch, n_episodes=20)
    handle = RldsAdapter().open(rlds_root, ScanConfig(path=str(rlds_root)))
    first = [ep.episode_id for ep in handle.iter_episodes(sample=Sampler(max_episodes=5, seed=3))]
    second = [ep.episode_id for ep in handle.iter_episodes(sample=Sampler(max_episodes=5, seed=3))]
    assert len(first) == 5
    assert first == second


def test_profile_hints_are_empty_because_rlds_declares_no_stats(
    rlds_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_stub(monkeypatch, n_episodes=2)
    handle = RldsAdapter().open(rlds_root, ScanConfig(path=str(rlds_root)))
    hints = handle.profile_hints()
    assert hints.declared_stats is None


def test_an_empty_dataset_is_a_clear_error(rlds_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stub(monkeypatch, n_episodes=0)
    with pytest.raises(ValueError, match="no episodes found"):
        RldsAdapter().open(rlds_root, ScanConfig(path=str(rlds_root)))


def test_a_missing_extra_asks_for_the_extra_by_name(rlds_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The layout is unambiguous, so "install this" beats "unknown format"."""
    monkeypatch.setattr("bohrin.adapters.rlds._available", lambda: False)
    with pytest.raises(ImportError, match=r"bohrin\[rlds\]"):
        RldsAdapter().open(rlds_root, ScanConfig(path=str(rlds_root)))


# ------------------------------------------------------------------------------- end to end


def test_a_full_scan_runs_over_a_stubbed_rlds_dataset(rlds_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real assurance: the whole pipeline works on RLDS-shaped data, not just the reader."""
    import bohrin

    _install_stub(monkeypatch, n_episodes=14)
    report = bohrin.scan(str(rlds_root))
    assert report.dataset.format == "rlds"
    assert report.dataset.n_episodes == 14
    assert report.dataset.action_dim == _ACTION_DIM
    assert report.detectors_run, "no detector ran on an RLDS dataset"
    assert any(d.startswith("vision.") for d in report.detectors_run)


def test_a_nested_language_instruction_is_found(rlds_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: much of Open-X nests the instruction under ``observation/``.

    ``_LANGUAGE_KEYS`` is matched with ``endswith`` precisely so a nested key qualifies, but the
    adapter decoded only top-level values — so a nested instruction stayed as raw bytes, failed
    the ``str`` test, and the dataset scanned as *unlabelled*. Silently dropping every task label
    would disable the whole LABEL family on the format it matters most for.
    """
    module = type(sys)("tensorflow_datasets")
    module.builder_from_directory = lambda path: _NestedInstructionBuilder(3, "fold the towel")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tensorflow_datasets", module)

    handle = RldsAdapter().open(rlds_root, ScanConfig(path=str(rlds_root)))
    episode = next(handle.iter_episodes(sample=Sampler()))
    assert episode.task is not None, "a nested language instruction was not picked up"
    assert episode.task.text == "fold the towel"


def test_nested_numeric_tensors_do_not_rely_on_tensorflow_conveniences(
    rlds_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A nested tensor must be unwrapped via ``.numpy()``, not via numpy's ``__array__`` luck."""
    module = type(sys)("tensorflow_datasets")
    module.builder_from_directory = lambda path: _NestedInstructionBuilder(3, "x")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tensorflow_datasets", module)

    handle = RldsAdapter().open(rlds_root, ScanConfig(path=str(rlds_root)))
    episode = next(handle.iter_episodes(sample=Sampler()))
    assert episode.steps.proprio is not None
    assert episode.steps.proprio.shape == (_LENGTH, _ACTION_DIM)
    assert np.isfinite(episode.steps.proprio).all()
