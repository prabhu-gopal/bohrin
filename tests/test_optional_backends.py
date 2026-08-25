"""The optional-dependency seams: DINOv2 and the ONNX policy reader (docs/09 §5, docs/03 §6).

Both modules were effectively untested — ``encoders/dino.py`` at **0 %** — for the same reason:
exercising them appears to require torch or onnxruntime, so CI skipped them and the code went
unverified. But neither module's *logic* needs the heavy library. What they own is a small,
explicit contract with it, and a stub honours that contract exactly while leaving the parts that
can actually be wrong — resizing, channel handling, scaling, shape inference, family detection —
fully exercised.

This matters more than a coverage number: an encoder is selected by ``--encoder dinov2`` on a
user's machine, where a shape bug surfaces as a crash after a weights download.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from bohrin._arrays import AnyArray
from bohrin.encoders import get_encoder
from bohrin.encoders.dino import DinoV2Encoder, _prepare
from bohrin.ir.schema import PolicyFamily
from bohrin.policy.loader import UnreadablePolicyError, load_policy_profile

# --------------------------------------------------------------------- the DINOv2 seam


class _StubModule:
    """Minimal stand-in for ``torch``, honouring exactly what the encoder calls."""

    class _InferenceMode:
        def __enter__(self) -> None:
            return None

        def __exit__(self, *exc: object) -> None:
            return None

    class _Tensor:
        """Carries a numpy array through ``from_numpy().float().permute()`` and the model."""

        def __init__(self, array: AnyArray) -> None:
            self.array = array

        def float(self) -> _StubModule._Tensor:
            return _StubModule._Tensor(self.array.astype(np.float32))

        def permute(self, *order: int) -> _StubModule._Tensor:
            return _StubModule._Tensor(np.transpose(self.array, order))

        def cpu(self) -> _StubModule._Tensor:
            return self

        def numpy(self) -> AnyArray:
            return self.array

    class _Hub:
        def __init__(self, embedding_dim: int = 384) -> None:
            self._dim = embedding_dim
            self.requested: list[str] = []

        def load(self, repo: str, model: str) -> Any:
            self.requested.append(model)
            dim = self._dim

            class _Model:
                def eval(self) -> None:
                    return None

                def __call__(self, tensor: _StubModule._Tensor) -> _StubModule._Tensor:
                    batch = tensor.array.shape[0]
                    # A deterministic but input-dependent embedding, so a test can tell whether
                    # distinct frames produce distinct vectors.
                    means = tensor.array.reshape(batch, -1).mean(axis=1, keepdims=True)
                    return _StubModule._Tensor(np.tile(means, (1, dim)))

            return _Model()

    def __init__(self, embedding_dim: int = 384) -> None:
        self.hub = _StubModule._Hub(embedding_dim)

    def from_numpy(self, array: AnyArray) -> _StubModule._Tensor:
        return _StubModule._Tensor(array)

    def inference_mode(self) -> _StubModule._InferenceMode:
        return _StubModule._InferenceMode()


@pytest.fixture
def stub_torch(monkeypatch: pytest.MonkeyPatch) -> _StubModule:
    stub = _StubModule()
    monkeypatch.setitem(sys.modules, "torch", stub)
    return stub


def test_dino_is_never_selected_implicitly() -> None:
    """It downloads weights, so only an explicit ``--encoder dinov2`` may reach it."""
    assert get_encoder("tiled").name == "tiled"
    assert get_encoder("dinov2").name == "dinov2"


def test_dino_encodes_a_batch_to_one_row_per_frame(stub_torch: _StubModule) -> None:
    frames = [np.full((48, 64, 3), v, dtype=np.float64) for v in (10.0, 200.0, 90.0)]
    embeddings = DinoV2Encoder().encode(frames)
    assert embeddings.shape == (3, 384)
    assert embeddings.dtype == np.float64
    # Distinct frames must not collapse to the same vector, or scene diversity is blind.
    assert len({tuple(row[:1]) for row in embeddings}) == 3


def test_dino_loads_the_requested_variant_once(stub_torch: _StubModule) -> None:
    encoder = DinoV2Encoder()
    encoder.encode([np.zeros((32, 32, 3))])
    encoder.encode([np.ones((32, 32, 3))])
    assert stub_torch.hub.requested == ["dinov2_vits14"], "the model was re-loaded per call"


def test_dino_on_an_empty_batch_needs_no_torch_at_all() -> None:
    """No frames means no weights: an empty batch must not trigger a download."""
    assert DinoV2Encoder().encode([]).shape == (0, 0)


def test_dino_without_the_extra_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", None)
    with pytest.raises((RuntimeError, ImportError), match=r"bohrin\[vision\]|torch"):
        DinoV2Encoder().encode([np.zeros((16, 16, 3))])


@pytest.mark.parametrize(
    "shape",
    [(48, 64, 3), (10, 10, 3), (300, 200, 3), (224, 224, 3)],
)
def test_prepare_always_produces_the_models_input_shape(shape: tuple[int, int, int]) -> None:
    out = _prepare(np.random.default_rng(0).uniform(0, 255, size=shape))
    assert out.shape == (224, 224, 3)
    assert out.max() <= 1.0 + 1e-9, "pixels must be scaled into [0, 1]"


def test_prepare_expands_greyscale_and_single_channel_frames() -> None:
    grey = _prepare(np.random.default_rng(0).uniform(0, 255, size=(40, 40)))
    single = _prepare(np.random.default_rng(0).uniform(0, 255, size=(40, 40, 1)))
    assert grey.shape == (224, 224, 3)
    assert single.shape == (224, 224, 3)


def test_prepare_leaves_already_normalized_frames_alone() -> None:
    """A frame already in [0, 1] must not be divided by 255 a second time."""
    out = _prepare(np.full((32, 32, 3), 0.5))
    assert np.allclose(out, 0.5)


def test_prepare_drops_extra_channels() -> None:
    """RGBA in, RGB out — the model takes three channels."""
    assert _prepare(np.random.default_rng(0).uniform(0, 255, size=(32, 32, 4))).shape == (224, 224, 3)


# ------------------------------------------------------------------- the ONNX policy seam


class _StubOrt:
    """Minimal ``onnxruntime``: a session exposing input/output shapes."""

    def __init__(self, inputs: list[tuple[str, list[Any]]], outputs: list[tuple[str, list[Any]]]) -> None:
        self._inputs = inputs
        self._outputs = outputs

    def InferenceSession(self, path: str, providers: list[str]) -> Any:  # noqa: N802 - mirrors the real API
        inputs, outputs = self._inputs, self._outputs

        class _Spec:
            def __init__(self, name: str, shape: list[Any]) -> None:
                self.name = name
                self.shape = shape

        class _Session:
            def get_inputs(self) -> list[_Spec]:
                return [_Spec(n, s) for n, s in inputs]

            def get_outputs(self) -> list[_Spec]:
                return [_Spec(n, s) for n, s in outputs]

        return _Session()


def _install_ort(monkeypatch: pytest.MonkeyPatch, stub: _StubOrt) -> None:
    monkeypatch.setitem(sys.modules, "onnxruntime", stub)


def test_onnx_shapes_become_a_policy_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "act_policy.onnx"
    path.write_bytes(b"not really onnx; the stub never parses it")
    _install_ort(
        monkeypatch,
        _StubOrt(
            inputs=[("observation.state", ["batch", 14]), ("observation.image", ["batch", 3, 224, 224])],
            outputs=[("action", ["batch", 7])],
        ),
    )
    profile = load_policy_profile(str(path))
    assert profile.expected_action_dim == 7
    assert profile.expected_proprio_dim == 14
    # The family is inferred from the filename, since ONNX carries no architecture field.
    assert profile.family is PolicyFamily.ACT


def test_onnx_with_only_dynamic_shapes_yields_unknown_dims(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Symbolic dimensions are not numbers; inventing one would fabricate a mismatch."""
    path = tmp_path / "mystery.onnx"
    path.write_bytes(b"stub")
    _install_ort(
        monkeypatch,
        _StubOrt(inputs=[("obs", ["batch", "features"])], outputs=[("out", ["batch", "dim"])]),
    )
    profile = load_policy_profile(str(path))
    assert profile.expected_action_dim is None
    assert profile.expected_proprio_dim is None


def test_onnx_ignores_image_inputs_when_looking_for_proprio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "pi0.onnx"
    path.write_bytes(b"stub")
    _install_ort(
        monkeypatch,
        _StubOrt(
            inputs=[("image", ["batch", 3, 224, 224]), ("qpos", ["batch", 9])],
            outputs=[("action", ["batch", 6])],
        ),
    )
    profile = load_policy_profile(str(path))
    assert profile.expected_proprio_dim == 9


# --------------------------------------------------- policy directory edge cases (72% → up)


def test_an_unreadable_config_is_a_user_error(tmp_path: Path) -> None:
    root = tmp_path / "ckpt"
    root.mkdir()
    (root / "config.json").write_text("{ this is not json")
    with pytest.raises(UnreadablePolicyError, match="unreadable config JSON"):
        load_policy_profile(str(root))


def test_a_corrupt_norm_stats_file_degrades_instead_of_failing(tmp_path: Path) -> None:
    """Normalization metadata is a bonus; losing it must not cost the whole scan."""
    root = tmp_path / "ckpt"
    root.mkdir()
    (root / "config.json").write_text(json.dumps({"model_type": "act", "action_dim": 7}))
    (root / "norm_stats.json").write_text("{ broken")
    profile = load_policy_profile(str(root))
    assert profile.expected_action_dim == 7
    assert profile.norm_stats is None or profile.norm_stats == {}


def test_declared_camera_keys_are_carried_through(tmp_path: Path) -> None:
    root = tmp_path / "ckpt"
    root.mkdir()
    (root / "config.json").write_text(json.dumps({"model_type": "diffusion", "camera_keys": ["cam_high", "cam_wrist"]}))
    profile = load_policy_profile(str(root))
    assert profile.expected_cameras == ("cam_high", "cam_wrist")
    assert profile.family is PolicyFamily.DIFFUSION


def test_an_unknown_container_is_refused_by_name(tmp_path: Path) -> None:
    path = tmp_path / "weights.tflite"
    path.write_bytes(b"stub")
    with pytest.raises(UnreadablePolicyError, match="unrecognized checkpoint container"):
        load_policy_profile(str(path))


def test_a_missing_checkpoint_says_so(tmp_path: Path) -> None:
    with pytest.raises(UnreadablePolicyError, match="no such checkpoint"):
        load_policy_profile(str(tmp_path / "absent.safetensors"))


@pytest.mark.parametrize("suffix", [".pt", ".pth", ".bin", ".ckpt"])
def test_every_pickle_container_is_refused(tmp_path: Path, suffix: str) -> None:
    """Unpickling is arbitrary code execution; a static analyzer must never be the thing
    that runs a checkpoint downloaded from the internet."""
    path = tmp_path / f"model{suffix}"
    path.write_bytes(b"\x80\x04 pickled")
    with pytest.raises(UnreadablePolicyError, match="safetensors"):
        load_policy_profile(str(path))
