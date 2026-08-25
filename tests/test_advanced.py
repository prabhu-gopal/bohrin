"""The advanced-method layer: visual encoders, Confident Learning, ANN scale (docs/09 §5)."""

from __future__ import annotations

import numpy as np
import pytest

import _synth
from bohrin._arrays import FloatArray, IntArray
from bohrin.analysis.confident_learning import (
    class_thresholds,
    confident_joint,
    label_error_mask,
    self_confidence,
)
from bohrin.analysis.neighbors import knn
from bohrin.detectors.coverage import SceneDiversityDetector
from bohrin.encoders import DEFAULT_ENCODER, TiledStatsEncoder, get_encoder

# --------------------------------------------------------------------------- encoders


def test_default_encoder_is_offline_and_dependency_free() -> None:
    encoder = get_encoder()
    assert encoder.name == DEFAULT_ENCODER == "tiled"
    assert isinstance(encoder, TiledStatsEncoder)


def test_encoder_embeds_frames_to_fixed_width() -> None:
    rng = np.random.default_rng(0)
    frames = [_synth.scene(rng) for _ in range(5)]
    out = get_encoder("tiled").encode(frames)
    assert out.shape[0] == 5
    assert out.shape[1] == 4 * 4 * 3 * 2  # grid × channels × (mean, std)


def test_encoder_separates_distinct_scenes() -> None:
    rng = np.random.default_rng(1)
    a, b = _synth.scene(rng), _synth.scene(rng)
    enc = get_encoder("tiled")
    same = enc.encode([a, a.copy()])
    diff = enc.encode([a, b])
    assert np.linalg.norm(same[0] - same[1]) < np.linalg.norm(diff[0] - diff[1])


def test_dinov2_is_never_selected_implicitly() -> None:
    # Loading DINOv2 downloads weights, so it must be requested by name (local-first).
    assert get_encoder().name != "dinov2"
    with pytest.raises(ValueError, match="unknown encoder"):
        get_encoder("not-a-real-encoder")


# ----------------------------------------------------------------- scene diversity


def test_scene_diversity_clean_and_injected() -> None:
    ctx_clean = _synth.build_context(_synth.vision_dataset(n_episodes=12))
    assert not list(SceneDiversityDetector().run(ctx_clean))

    ctx_single = _synth.build_context(_synth.vision_dataset(n_episodes=12, single_scene=True))
    findings = list(SceneDiversityDetector().run(ctx_single))
    assert findings
    assert "distinct scene" in findings[0].title
    assert "Data Scaling Laws" in findings[0].mechanism


# ------------------------------------------------------------- confident learning


def _toy_problem() -> tuple[IntArray, FloatArray]:
    """Ten examples, two classes, confidently predicted; index 3 is labelled wrong."""
    labels = np.array([0, 0, 0, 0, 0, 1, 1, 1, 1, 1], dtype=np.int64)
    probs = np.tile(np.array([0.9, 0.1]), (10, 1))
    probs[5:] = [0.1, 0.9]
    probs[3] = [0.1, 0.9]  # trajectory says class 1, label says class 0
    return labels, probs


def test_class_thresholds_are_per_class_self_confidence() -> None:
    labels, probs = _toy_problem()
    thresholds = class_thresholds(labels, probs)
    assert thresholds.shape == (2,)
    # Class 0's threshold is dragged down by the mislabeled example, as CL intends.
    assert 0.0 < thresholds[0] < 0.9
    assert thresholds[1] == pytest.approx(0.9)


def test_confident_joint_puts_the_error_off_diagonal() -> None:
    labels, probs = _toy_problem()
    joint = confident_joint(labels, probs)
    assert joint.shape == (2, 2)
    assert joint[0, 1] >= 1  # labelled 0, confidently 1
    assert joint.sum() >= 9


def test_label_error_mask_finds_exactly_the_planted_error() -> None:
    labels, probs = _toy_problem()
    mask = label_error_mask(labels, probs)
    assert mask.tolist() == [False, False, False, True, False, False, False, False, False, False]


def test_self_confidence_is_low_for_the_error() -> None:
    labels, probs = _toy_problem()
    conf = self_confidence(labels, probs)
    assert conf[3] < 0.5
    assert conf[0] > 0.5


def test_clean_labels_produce_no_errors() -> None:
    labels = np.array([0, 0, 0, 1, 1, 1], dtype=np.int64)
    probs = np.array([[0.9, 0.1]] * 3 + [[0.1, 0.9]] * 3)
    assert not label_error_mask(labels, probs).any()


# ------------------------------------------------------------------- scale/ANN


def test_knn_is_exact_and_correct_without_faiss() -> None:
    points = np.array([[0.0, 0.0], [0.1, 0.0], [5.0, 5.0], [5.1, 5.0]])
    dist, idx = knn(points, 1)
    assert idx[:, 0].tolist() == [1, 0, 3, 2]  # each point's true nearest neighbour
    assert np.allclose(dist[:, 0], [0.1, 0.1, 0.1, 0.1])


def test_multimodality_bounds_its_neighbour_search() -> None:
    # The detector must cap the pooled steps it feeds to kNN, so a big reservoir cannot
    # blow up the search. 60 episodes × 48 steps = 2880 rows; the cap is a constant.
    from bohrin.detectors.multimodality import _MAX_STATES

    assert _MAX_STATES <= 20_000
    ctx = _synth.build_context(_synth.contradictory_dataset(n_episodes=20))
    from bohrin.detectors.multimodality import ContradictoryActionsDetector

    assert list(ContradictoryActionsDetector().run(ctx))  # still fires under the cap
