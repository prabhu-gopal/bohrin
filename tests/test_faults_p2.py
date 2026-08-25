"""Phase-2 fault-injection fixtures — the "aha" detectors (docs/06 P2 DoD).

Same contract as the Phase-1 suite: clean data must produce **no** finding, and the matching
injected defect must produce at least one. The three named P2 acceptance criteria
(mode-collapse narration, inverse-dynamics catching a teleport, multimodality recommending
Diffusion Policy) are asserted explicitly at the bottom.
"""

from __future__ import annotations

import _synth
from bohrin.detectors.base import AnalysisContext, Detector
from bohrin.detectors.causal import ProprioShortcutDetector
from bohrin.detectors.consistency import (
    DurationVarianceDetector,
    OperatorStyleDetector,
    TrajectoryAlignmentDetector,
)
from bohrin.detectors.coverage import (
    InitialConditionDiversityDetector,
    ModeCollapseDetector,
    RedundancyDetector,
)
from bohrin.detectors.dynamics import ForwardResidualDetector, InverseResidualDetector
from bohrin.detectors.label import MissingLabelDetector, TrajectoryLabelMismatchDetector
from bohrin.detectors.multimodality import ContradictoryActionsDetector, LabelConflictDetector
from bohrin.detectors.stats import DistributionDriftDetector
from bohrin.detectors.vision import (
    BlurExposureDetector,
    CameraDropoutDetector,
    DepthQualityDetector,
    FrozenFramesDetector,
    ViewpointDriftDetector,
)
from bohrin.ir.schema import PolicyFamily, PolicyProfile, Severity


def _fires(detector: Detector, ctx: AnalysisContext) -> bool:
    return len(list(detector.run(ctx))) > 0


def _clean() -> AnalysisContext:
    return _synth.build_context(_synth.clean_dataset(n_episodes=16))


def _clean_vision() -> AnalysisContext:
    return _synth.build_context(_synth.vision_dataset())


# --------------------------------------------------------------------------- COVERAGE


def test_mode_collapse() -> None:
    assert not _fires(ModeCollapseDetector(), _clean())
    assert _fires(ModeCollapseDetector(), _synth.build_context(_synth.single_strategy_dataset()))


def test_initial_condition_diversity() -> None:
    assert not _fires(InitialConditionDiversityDetector(), _clean())
    ctx = _synth.build_context(_synth.narrow_init_dataset())
    assert _fires(InitialConditionDiversityDetector(), ctx)


def test_redundancy() -> None:
    assert not _fires(RedundancyDetector(), _clean())
    assert _fires(RedundancyDetector(), _synth.build_context(_synth.redundant_dataset()))


# --------------------------------------------------------------------------- DYNAMICS


def test_inverse_residual() -> None:
    assert not _fires(InverseResidualDetector(), _clean())
    assert _fires(InverseResidualDetector(), _synth.build_context(_synth.teleport_dataset()))


def test_forward_residual() -> None:
    assert not _fires(ForwardResidualDetector(), _clean())
    assert _fires(ForwardResidualDetector(), _synth.build_context(_synth.teleport_dataset()))


# ----------------------------------------------------------------------- MULTIMODALITY


def test_contradictory_actions() -> None:
    assert not _fires(ContradictoryActionsDetector(), _clean())
    ctx = _synth.build_context(_synth.contradictory_dataset())
    assert _fires(ContradictoryActionsDetector(), ctx)


def test_label_conflict() -> None:
    assert not _fires(LabelConflictDetector(), _clean())
    # Two tasks that begin from indistinguishable states.
    episodes = _synth.contradictory_dataset(n_episodes=16)
    tagged = [
        _synth.with_task(ep, "open the drawer" if i % 2 == 0 else "fold the towel") for i, ep in enumerate(episodes)
    ]
    assert _fires(LabelConflictDetector(), _synth.build_context(tagged))


# ------------------------------------------------------------------------- CONSISTENCY


def test_operator_style() -> None:
    assert not _fires(OperatorStyleDetector(), _clean())
    assert _fires(OperatorStyleDetector(), _synth.build_context(_synth.two_style_dataset()))


def test_trajectory_alignment() -> None:
    assert not _fires(TrajectoryAlignmentDetector(), _clean())
    ctx = _synth.build_context(_synth.dtw_outlier_dataset())
    assert _fires(TrajectoryAlignmentDetector(), ctx)


def test_duration_variance() -> None:
    assert not _fires(DurationVarianceDetector(), _clean())
    ctx = _synth.build_context(_synth.varied_duration_dataset())
    assert _fires(DurationVarianceDetector(), ctx)


# ------------------------------------------------------------------------------ LABEL


def test_missing_label() -> None:
    assert not _fires(MissingLabelDetector(), _clean())  # unlabelled dataset → not our business
    ctx = _synth.build_context(_synth.labelled_dataset(drop_labels=4))
    assert _fires(MissingLabelDetector(), ctx)


def test_trajectory_label_mismatch() -> None:
    assert not _fires(TrajectoryLabelMismatchDetector(), _synth.build_context(_synth.labelled_dataset()))
    ctx = _synth.build_context(_synth.labelled_dataset(mislabel_at=4))
    assert _fires(TrajectoryLabelMismatchDetector(), ctx)


# ------------------------------------------------------------------- STATS / CAUSAL


def test_distribution_drift() -> None:
    assert not _fires(DistributionDriftDetector(), _clean())
    assert _fires(DistributionDriftDetector(), _synth.build_context(_synth.drift_dataset()))


def test_proprio_shortcut() -> None:
    assert not _fires(ProprioShortcutDetector(), _clean())
    ctx = _synth.build_context(_synth.proprio_shortcut_dataset())
    assert _fires(ProprioShortcutDetector(), ctx)


# ----------------------------------------------------------------------------- VISION


def test_frozen_frames() -> None:
    assert not _fires(FrozenFramesDetector(), _clean_vision())
    ctx = _synth.build_context(_synth.vision_dataset(frozen_at=2))
    assert _fires(FrozenFramesDetector(), ctx)


def test_blur_exposure() -> None:
    assert not _fires(BlurExposureDetector(), _clean_vision())
    assert _fires(BlurExposureDetector(), _synth.build_context(_synth.vision_dataset(blur=True)))


def test_camera_dropout() -> None:
    assert not _fires(CameraDropoutDetector(), _clean_vision())
    ctx = _synth.build_context(_synth.vision_dataset(drop_camera_at=1))
    assert _fires(CameraDropoutDetector(), ctx)


def test_viewpoint_drift() -> None:
    assert not _fires(ViewpointDriftDetector(), _clean_vision())
    ctx = _synth.build_context(_synth.vision_dataset(viewpoint_shift_at=5))
    assert _fires(ViewpointDriftDetector(), ctx)


def test_depth_quality() -> None:
    assert not _fires(DepthQualityDetector(), _clean_vision())
    ctx = _synth.build_context(_synth.vision_dataset(depth_holes=True))
    assert _fires(DepthQualityDetector(), ctx)


# ------------------------------------------------------- the three named P2 criteria


def test_dod_mode_collapse_narrates_one_way() -> None:
    ctx = _synth.build_context(_synth.single_strategy_dataset())
    finding = next(iter(ModeCollapseDetector().run(ctx)))
    assert finding.severity is Severity.HIGH
    assert "one strategy" in finding.title
    assert "only ever learns one way" in finding.mechanism
    assert "diversity" in finding.fix.text.lower()


def test_dod_inverse_dynamics_catches_teleport() -> None:
    ctx = _synth.build_context(_synth.teleport_dataset())
    finding = next(iter(InverseResidualDetector().run(ctx)))
    assert finding.severity is Severity.HIGH
    assert "don't explain" in finding.title
    assert finding.locus.episodes  # localized to specific episodes
    # The title leads with the measured transition rate rather than only an episode count, so a
    # diffuse defect cannot read as "every one of these episodes is ruined".
    assert "of transitions" in finding.title
    assert 0.0 < finding.blast_radius.frac_steps < 1.0


def test_dod_multimodality_recommends_diffusion() -> None:
    ctx = _synth.build_context(_synth.contradictory_dataset())
    finding = next(iter(ContradictoryActionsDetector().run(ctx)))
    assert finding.severity is Severity.HIGH  # no policy given → unimodal head assumed
    assert "Diffusion" in finding.fix.text
    assert finding.fix.machine["recommended"] == "diffusion"


def test_dod_multimodality_is_policy_weighted() -> None:
    # The same defect is de-emphasized when the target model can represent multiple modes.
    base = _synth.build_context(_synth.contradictory_dataset())
    ctx = _synth.build_context(
        _synth.contradictory_dataset(),
        config=base.config,
    )
    diffusion_ctx = AnalysisContext(
        profile=ctx.profile,
        schema=ctx.schema,
        episodes=ctx.episodes,
        config=ctx.config,
        rng=ctx.rng,
        policy=PolicyProfile(family=PolicyFamily.DIFFUSION),
    )
    finding = next(iter(ContradictoryActionsDetector().run(diffusion_ctx)))
    assert finding.severity is Severity.LOW


def test_clean_data_produces_no_findings_from_any_detector() -> None:
    from bohrin.detectors.registry import discover

    ctx = _clean()
    for det in discover():
        assert not _fires(det, ctx), f"{det.id} fired on clean data"
