"""Fault-injection fixtures — the validate-the-validator suite (docs/07 §8, docs/06 P1).

For every detector: a *clean* dataset must produce **no** finding, and a dataset with the
matching defect injected must produce **at least one**. This is the measured precision/
recall seed the P4 benchmark assembles.
"""

from __future__ import annotations

import numpy as np

import _synth
from bohrin.detectors.base import AnalysisContext, Detector
from bohrin.detectors.causal import CopycatShortcutDetector
from bohrin.detectors.integrity import (
    DeclaredMismatchDetector,
    DuplicateFramesDetector,
    NanInfDetector,
    ShapeDtypeDetector,
    TimestampRegularityDetector,
    TruncatedEpisodesDetector,
)
from bohrin.detectors.smoothness import DiscontinuityJumpDetector, JerkOutlierDetector
from bohrin.detectors.stats import (
    DeadDimensionDetector,
    NormalizationOutliersDetector,
    SaturationClippingDetector,
)
from bohrin.detectors.temporal import ActionObservationLagDetector, IdleFramesDetector
from bohrin.ir.schema import FeatureStats, SchemaHints


def _fires(detector: Detector, ctx: AnalysisContext) -> bool:
    return len(list(detector.run(ctx))) > 0


def _clean_ctx() -> AnalysisContext:
    return _synth.build_context(_synth.clean_dataset(n_episodes=16))


# --------------------------------------------------------------------------- INTEGRITY


def test_nan_inf() -> None:
    assert not _fires(NanInfDetector(), _clean_ctx())
    eps = _synth.clean_dataset(n_episodes=16)
    eps[2] = _synth.inject_nan(eps[2])
    assert _fires(NanInfDetector(), _synth.build_context(eps))


def test_shape_dtype() -> None:
    assert not _fires(ShapeDtypeDetector(), _clean_ctx())
    eps = _synth.clean_dataset(n_episodes=16)
    eps[1] = _synth.inject_shape_mismatch(eps[1])
    assert _fires(ShapeDtypeDetector(), _synth.build_context(eps))


def test_timestamp_regularity() -> None:
    assert not _fires(TimestampRegularityDetector(), _clean_ctx())
    eps = _synth.clean_dataset(n_episodes=16)
    eps[0] = _synth.inject_timestamp_gap(eps[0])
    assert _fires(TimestampRegularityDetector(), _synth.build_context(eps))


def test_duplicate_frames() -> None:
    assert not _fires(DuplicateFramesDetector(), _clean_ctx())
    eps = _synth.clean_dataset(n_episodes=16)
    eps[3] = _synth.inject_duplicate_run(eps[3])
    assert _fires(DuplicateFramesDetector(), _synth.build_context(eps))


def test_truncated_episodes() -> None:
    assert not _fires(TruncatedEpisodesDetector(), _clean_ctx())
    ctx = _synth.build_context(_synth.truncated_dataset())
    assert _fires(TruncatedEpisodesDetector(), ctx)


def test_declared_mismatch() -> None:
    assert not _fires(DeclaredMismatchDetector(), _clean_ctx())  # no declared stats
    stale = SchemaHints(declared_stats={"action": FeatureStats(mean=0.0, std=10.0, min=-30.0, max=30.0)})
    ctx = _synth.build_context(_synth.clean_dataset(n_episodes=16), hints=stale)
    assert _fires(DeclaredMismatchDetector(), ctx)


# --------------------------------------------------------------------------- STATS


def test_dead_dimension() -> None:
    assert not _fires(DeadDimensionDetector(), _clean_ctx())
    ctx = _synth.build_context(_synth.inject_dead_dimension(_synth.clean_dataset(), dim=3))
    findings = list(DeadDimensionDetector().run(ctx))
    assert findings and findings[0].locus.dimensions == [3]


def test_saturation_clipping() -> None:
    assert not _fires(SaturationClippingDetector(), _clean_ctx())
    ctx = _synth.build_context(_synth.inject_saturation(_synth.clean_dataset(), dim=0))
    assert _fires(SaturationClippingDetector(), ctx)


def test_normalization_outliers() -> None:
    assert not _fires(NormalizationOutliersDetector(), _clean_ctx())
    eps = _synth.clean_dataset(n_episodes=16)
    eps[0] = _synth.inject_outlier(eps[0], dim=0, value=50.0)
    assert _fires(NormalizationOutliersDetector(), _synth.build_context(eps))


# --------------------------------------------------------------------------- SMOOTHNESS


def test_jerk_outlier() -> None:
    assert not _fires(JerkOutlierDetector(), _clean_ctx())
    eps = _synth.clean_dataset(n_episodes=16)
    eps[5] = _synth.inject_jerk(eps[5])
    assert _fires(JerkOutlierDetector(), _synth.build_context(eps))


def test_discontinuity_jump() -> None:
    assert not _fires(DiscontinuityJumpDetector(), _clean_ctx())
    eps = _synth.clean_dataset(n_episodes=16)
    eps[4] = _synth.inject_jump(eps[4])
    assert _fires(DiscontinuityJumpDetector(), _synth.build_context(eps))


# --------------------------------------------------------------------------- TEMPORAL


def test_idle_frames() -> None:
    assert not _fires(IdleFramesDetector(), _clean_ctx())
    eps = _synth.clean_dataset(n_episodes=16)
    eps[6] = _synth.inject_idle(eps[6])
    assert _fires(IdleFramesDetector(), _synth.build_context(eps))


def test_action_observation_lag() -> None:
    assert not _fires(ActionObservationLagDetector(), _clean_ctx())
    ctx = _synth.build_context(_synth.inject_lag(_synth.clean_dataset(n_episodes=16), shift=2))
    assert _fires(ActionObservationLagDetector(), ctx)


# --------------------------------------------------------------------------- CAUSAL


def test_copycat_shortcut() -> None:
    assert not _fires(CopycatShortcutDetector(), _clean_ctx())
    ctx = _synth.build_context(_synth.copycat_dataset())
    assert _fires(CopycatShortcutDetector(), ctx)


# --------------------------------------------------------------------------- clean sweep


def test_clean_data_produces_no_findings_from_any_detector() -> None:
    from bohrin.detectors.registry import discover

    ctx = _clean_ctx()
    for det in discover():
        assert not _fires(det, ctx), f"{det.id} fired on clean data"


def test_conformal_bounds_false_positive_rate() -> None:
    # docs/06 P1 DoD: --fpr provably bounds false positives on a clean (in-distribution) set.
    from bohrin.calibrate.conformal import ConformalCalibrator

    rng = np.random.default_rng(0)
    scores = rng.normal(size=5000)
    flagged = ConformalCalibrator(fpr=0.01).calibrate(scores).is_anomaly.mean()
    assert flagged <= 0.02  # ≈ fpr, with finite-sample slack
