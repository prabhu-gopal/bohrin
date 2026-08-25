"""The fault-injection benchmark and its CI quality gate (docs/06 P4 DoD, docs/08 §4).

This is "validate the validator": every detector's recall, false-positive rate and ROC-AUC
are *measured* across many seeded clean/faulted pairs, and the build **fails** if any of them
drops below its floor. A silent regression in detector quality — a threshold nudged too far,
a refactor that breaks a gate — turns this suite red instead of shipping.

The scenarios pull the test-only synthetic generators; the reusable measurement machinery
lives in the shipped :mod:`bohrin.bench` package and is unit-tested in ``test_bench_harness``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import numpy as np
import pytest

import _synth
from bohrin.bench import Scenario, run_scenario
from bohrin.bench.harness import ContextFactory, DetectorMetrics, format_table, run_benchmark
from bohrin.detectors.base import AnalysisContext
from bohrin.detectors.causal import CopycatShortcutDetector, ProprioShortcutDetector
from bohrin.detectors.consistency import (
    DurationVarianceDetector,
    OperatorStyleDetector,
    TrajectoryAlignmentDetector,
)
from bohrin.detectors.coverage import (
    InitialConditionDiversityDetector,
    ModeCollapseDetector,
    RedundancyDetector,
    SceneDiversityDetector,
    TaskImbalanceDetector,
)
from bohrin.detectors.dynamics import ForwardResidualDetector, InverseResidualDetector
from bohrin.detectors.integrity import (
    DeclaredMismatchDetector,
    DuplicateFramesDetector,
    NanInfDetector,
    ShapeDtypeDetector,
    SplitLeakageDetector,
    TimestampRegularityDetector,
    TruncatedEpisodesDetector,
)
from bohrin.detectors.kinematics import (
    CurvatureDetector,
    GripperChatterDetector,
    NonMarkovianPauseDetector,
    PathEfficiencyDetector,
)
from bohrin.detectors.label import MissingLabelDetector, TrajectoryLabelMismatchDetector
from bohrin.detectors.multimodality import ContradictoryActionsDetector, LabelConflictDetector
from bohrin.detectors.policy_data import (
    ActionSpaceMismatchDetector,
    DimMismatchDetector,
    MissingProprioDetector,
    NormalizationMismatchDetector,
    OodEstimateDetector,
)
from bohrin.detectors.registry import discover as discover_detectors
from bohrin.detectors.scale import ConstantOrDegenerateChannelDetector, UnitScaleInconsistencyDetector
from bohrin.detectors.smoothness import DiscontinuityJumpDetector, JerkOutlierDetector
from bohrin.detectors.stats import (
    DeadDimensionDetector,
    DistributionDriftDetector,
    NormalizationOutliersDetector,
    SaturationClippingDetector,
)
from bohrin.detectors.temporal import ActionObservationLagDetector, IdleFramesDetector
from bohrin.detectors.vision import (
    BlurExposureDetector,
    CameraDropoutDetector,
    CompressionArtifactsDetector,
    DepthQualityDetector,
    FrozenFramesDetector,
    ViewpointDriftDetector,
)
from bohrin.ir.episode import Episode
from bohrin.ir.schema import ActionSpace, PolicyFamily

_SEEDS = 15
_N = 16

# --------------------------------------------------------------------- scenario helpers


def _ctx(episodes: list[Episode]) -> AnalysisContext:
    return _synth.build_context(episodes)


def _clean(seed: int) -> AnalysisContext:
    return _ctx(_synth.clean_dataset(n_episodes=_N, seed=seed))


def _per_episode(inject: Callable[[Episode], Episode]) -> ContextFactory:
    """A faulted factory that injects a single-episode defect into episode 2."""

    def factory(seed: int) -> AnalysisContext:
        eps = _synth.clean_dataset(n_episodes=_N, seed=seed)
        eps[2] = inject(eps[2])
        return _ctx(eps)

    return factory


def _dataset(inject: Callable[[list[Episode]], list[Episode]]) -> ContextFactory:
    """A faulted factory that injects a dataset-wide defect."""

    def factory(seed: int) -> AnalysisContext:
        return _ctx(inject(_synth.clean_dataset(n_episodes=_N, seed=seed)))

    return factory


def _from(builder: Callable[..., list[Episode]]) -> ContextFactory:
    """A factory that builds a purpose-made dataset (its own clean/faulted shape).

    Tolerates builders that don't take a ``seed`` — some synthetic datasets are fixed by
    construction — so a scenario still runs ``seeds`` trials (identical, which is fine: a
    deterministic defect either fires every time or the detector is broken).
    """
    import inspect

    takes_seed = "seed" in inspect.signature(builder).parameters

    def factory(seed: int) -> AnalysisContext:
        return _ctx(builder(seed=seed) if takes_seed else builder())

    return factory


def _built(builder: Callable[..., list[Episode]], **kwargs: Any) -> ContextFactory:
    """A factory over a purpose-made dataset builder with fixed keyword arguments."""

    def factory(seed: int) -> AnalysisContext:
        return _ctx(builder(seed=seed, **kwargs))

    return factory


def _vision(
    *,
    frozen_at: int | None = None,
    blur: bool = False,
    drop_camera_at: int | None = None,
    viewpoint_shift_at: int | None = None,
    depth_holes: bool = False,
    single_scene: bool = False,
    blown_out: bool = False,
    flat_backdrop: bool = False,
) -> ContextFactory:
    """A vision factory on a schema that *declares* its cameras (see ``_synth.vision_schema``)."""

    def factory(seed: int) -> AnalysisContext:
        return _synth.build_context(
            _synth.vision_dataset(
                seed=seed,
                frozen_at=frozen_at,
                blur=blur,
                drop_camera_at=drop_camera_at,
                viewpoint_shift_at=viewpoint_shift_at,
                depth_holes=depth_holes,
                single_scene=single_scene,
                blown_out=blown_out,
                flat_backdrop=flat_backdrop,
            ),
            schema=_synth.vision_schema(),
        )

    return factory


def _blocky(*, blocky: bool) -> ContextFactory:
    def factory(seed: int) -> AnalysisContext:
        return _synth.build_context(
            _synth.blocky_vision_dataset(seed=seed, blocky=blocky),
            schema=_synth.vision_schema(keys=("front",)),
        )

    return factory


def _declared(multiple: float) -> ContextFactory:
    """Declared-stats hints that agree with the data (``multiple == 1``) or are stale."""

    def factory(seed: int) -> AnalysisContext:
        episodes = _synth.clean_dataset(n_episodes=_N, seed=seed)
        measured = _synth.build_context(episodes).profile.action.std
        typical = float(np.median(measured[measured > 0]))
        return _synth.build_context(episodes, hints=_synth.declared_stats_hints(std=typical * multiple))

    return factory


def _with_policy(
    *,
    episodes: Callable[[int], list[Episode]] | None = None,
    schema_kwargs: dict[str, Any] | None = None,
    **policy_kwargs: Any,
) -> ContextFactory:
    """A context carrying a parsed :class:`PolicyProfile` — the POLICY↔DATA family's input.

    These detectors are inert without ``--policy``, so their "fault" lives in the checkpoint
    metadata rather than in the data. The clean and faulted factories therefore differ in the
    policy profile (or the declared action space), not in the episodes.
    """

    def factory(seed: int) -> AnalysisContext:
        eps = episodes(seed) if episodes is not None else _synth.clean_dataset(n_episodes=_N, seed=seed)
        schema = _synth.make_schema(**(schema_kwargs or {}))
        return _synth.build_context(eps, schema=schema, policy=_synth.policy_profile(**policy_kwargs))

    return factory


def _norm_multiple(multiple: float) -> ContextFactory:
    """A policy whose baked-in q99 is ``multiple`` × the dataset's measured q99."""

    def factory(seed: int) -> AnalysisContext:
        episodes = _synth.clean_dataset(n_episodes=_N, seed=seed)
        measured = float(np.median(_synth.build_context(episodes).profile.action.q99))
        return _synth.build_context(episodes, policy=_synth.policy_profile(norm_q99=measured * multiple))

    return factory


def _split_clean(seed: int) -> AnalysisContext:
    eps = _synth.clean_dataset(n_episodes=_N, seed=seed)
    return _ctx([replace(ep, split="train" if i < 12 else "val") for i, ep in enumerate(eps)])


def _split_leaked(seed: int) -> AnalysisContext:
    eps = _synth.clean_dataset(n_episodes=_N, seed=seed)
    tagged = [replace(ep, split="train" if i < 12 else "val") for i, ep in enumerate(eps)]
    for i in range(12, _N):
        src = tagged[i - 12]
        tagged[i] = replace(src, episode_id=f"leaked_{i}", split="val")
    return _ctx(tagged)


# Each scenario: detector, a clean factory (must stay silent), a faulted one (must fire).
# Every registered detector must appear here or in EXEMPT below — enforced by
# ``test_every_registered_detector_is_measured``.
SCENARIOS: list[Scenario] = [
    # ---------------------------------------------------------------- INTEGRITY (Family A)
    Scenario(NanInfDetector(), _clean, _per_episode(_synth.inject_nan), name="integrity.nan_inf"),
    Scenario(ShapeDtypeDetector(), _clean, _per_episode(_synth.inject_shape_mismatch)),
    Scenario(TimestampRegularityDetector(), _clean, _per_episode(_synth.inject_timestamp_gap)),
    Scenario(DuplicateFramesDetector(), _clean, _per_episode(_synth.inject_duplicate_run)),
    Scenario(TruncatedEpisodesDetector(), _clean, _from(_synth.truncated_dataset)),
    Scenario(DeclaredMismatchDetector(), _declared(1.0), _declared(5.0)),
    Scenario(SplitLeakageDetector(), _split_clean, _split_leaked),
    # -------------------------------------------------------------------- STATS (Family B)
    Scenario(DeadDimensionDetector(), _clean, _dataset(_synth.inject_dead_dimension)),
    Scenario(SaturationClippingDetector(), _clean, _dataset(_synth.inject_saturation)),
    Scenario(NormalizationOutliersDetector(), _clean, _per_episode(_synth.inject_outlier)),
    Scenario(DistributionDriftDetector(), _built(_synth.clean_dataset, length=48), _from(_synth.drift_dataset)),
    Scenario(
        ConstantOrDegenerateChannelDetector(),
        _built(_synth.clean_dataset, n_episodes=12),
        _from(_synth.degenerate_channel_dataset),
    ),
    Scenario(
        UnitScaleInconsistencyDetector(),
        _built(_synth.clean_dataset, n_episodes=12),
        _from(_synth.mixed_units_dataset),
    ),
    # --------------------------------------------------------------- SMOOTHNESS (Family C)
    Scenario(JerkOutlierDetector(), _clean, _per_episode(_synth.inject_jerk)),
    Scenario(DiscontinuityJumpDetector(), _clean, _per_episode(_synth.inject_jump)),
    Scenario(
        PathEfficiencyDetector(),
        _built(_synth.wandering_dataset, wander_at=()),
        _from(_synth.wandering_dataset),
    ),
    Scenario(
        CurvatureDetector(),
        _from(_synth.smooth_dataset),
        _built(_synth.smooth_dataset, erratic_at=(3,)),
        name="smoothness.curvature",
    ),
    # ----------------------------------------------------------------- TEMPORAL (Family D)
    Scenario(IdleFramesDetector(), _clean, _per_episode(_synth.inject_idle)),
    Scenario(ActionObservationLagDetector(), _clean, _dataset(_synth.inject_lag)),
    Scenario(
        GripperChatterDetector(),
        _from(_synth.steady_gripper_dataset),
        _from(_synth.chattering_gripper_dataset),
    ),
    Scenario(
        NonMarkovianPauseDetector(),
        _built(_synth.clean_dataset, n_episodes=12),
        _from(_synth.pause_conflict_dataset),
    ),
    # ----------------------------------------------------------------- COVERAGE (Family E)
    Scenario(ModeCollapseDetector(), _from(_synth.clean_dataset), _from(_synth.single_strategy_dataset)),
    Scenario(RedundancyDetector(), _from(_synth.clean_dataset), _from(_synth.redundant_dataset)),
    Scenario(
        InitialConditionDiversityDetector(),
        _from(_synth.clean_dataset),
        _from(_synth.narrow_init_dataset),
    ),
    Scenario(SceneDiversityDetector(), _vision(), _vision(single_scene=True)),
    Scenario(
        TaskImbalanceDetector(),
        _from(_synth.balanced_task_dataset),
        _from(_synth.imbalanced_task_dataset),
    ),
    # -------------------------------------------------------------- CONSISTENCY (Family F)
    Scenario(OperatorStyleDetector(), _from(_synth.clean_dataset), _from(_synth.two_style_dataset)),
    Scenario(
        TrajectoryAlignmentDetector(),
        _built(_synth.clean_dataset, n_episodes=12),
        _from(_synth.dtw_outlier_dataset),
    ),
    Scenario(
        DurationVarianceDetector(),
        _built(_synth.clean_dataset, length=48),
        _from(_synth.varied_duration_dataset),
    ),
    # ------------------------------------------------------------ MULTIMODALITY (Family G)
    Scenario(ContradictoryActionsDetector(), _from(_synth.clean_dataset), _from(_synth.contradictory_dataset)),
    Scenario(
        LabelConflictDetector(),
        _built(_synth.shared_start_dataset, shared=False),
        _built(_synth.shared_start_dataset, shared=True),
    ),
    # ------------------------------------------------------------------- VISION (Family H)
    Scenario(FrozenFramesDetector(), _vision(), _vision(frozen_at=2)),
    Scenario(BlurExposureDetector(), _vision(), _vision(blur=True)),
    # The *exposure* half of this detector, whose clean case is a rendered flat backdrop rather
    # than a plain scene. That branch had no scenario at all, and shipped a false positive on
    # `lerobot/pusht`: 84 % of its pixels are pinned at white because the benchmark renders a
    # white background, which scored "100 % of frames badly exposed" on crisp images.
    Scenario(
        BlurExposureDetector(),
        _vision(flat_backdrop=True),
        _vision(blown_out=True),
        name="vision.blur_exposure[overexposure]",
    ),
    Scenario(CameraDropoutDetector(), _vision(), _vision(drop_camera_at=3)),
    Scenario(ViewpointDriftDetector(), _vision(single_scene=True), _vision(viewpoint_shift_at=5)),
    Scenario(DepthQualityDetector(), _vision(), _vision(depth_holes=True)),
    Scenario(CompressionArtifactsDetector(), _blocky(blocky=False), _blocky(blocky=True)),
    # -------------------------------------------------------------------- LABEL (Family I)
    Scenario(
        MissingLabelDetector(),
        _from(_synth.labelled_dataset),
        _built(_synth.labelled_dataset, drop_labels=4),
    ),
    Scenario(
        TrajectoryLabelMismatchDetector(),
        _from(_synth.labelled_dataset),
        _built(_synth.labelled_dataset, mislabel_at=5),
    ),
    # ------------------------------------------------------------- POLICY↔DATA (Family J)
    Scenario(
        DimMismatchDetector(),
        _with_policy(action_dim=6),
        _with_policy(action_dim=7),
    ),
    Scenario(
        MissingProprioDetector(),
        _with_policy(family=PolicyFamily.VLA_PI0),
        _with_policy(
            family=PolicyFamily.VLA_PI0,
            episodes=lambda seed: [_synth.strip_proprio(ep) for ep in _synth.clean_dataset(n_episodes=_N, seed=seed)],
            schema_kwargs={"proprio_dim": None},
        ),
    ),
    Scenario(NormalizationMismatchDetector(), _norm_multiple(1.0), _norm_multiple(0.125)),
    Scenario(
        ActionSpaceMismatchDetector(),
        _with_policy(family=PolicyFamily.VLA_OPENVLA, schema_kwargs={"action_space": ActionSpace.EEF_DELTA}),
        _with_policy(family=PolicyFamily.VLA_OPENVLA, schema_kwargs={"action_space": ActionSpace.JOINT_POS}),
    ),
    Scenario(OodEstimateDetector(), _norm_multiple(50.0), _norm_multiple(0.05)),
    # ----------------------------------------------------------------- DYNAMICS (Family K)
    Scenario(InverseResidualDetector(), _clean, _from(_synth.teleport_dataset)),
    Scenario(
        ForwardResidualDetector(),
        _built(_synth.clean_dataset, n_episodes=12),
        _from(_synth.teleport_dataset),
    ),
    # ------------------------------------------------------------------- CAUSAL (Family L)
    Scenario(
        CopycatShortcutDetector(),
        _built(_synth.clean_dataset, n_episodes=12),
        _from(_synth.copycat_dataset),
    ),
    Scenario(
        ProprioShortcutDetector(),
        _built(_synth.clean_dataset, n_episodes=12),
        _from(_synth.proprio_shortcut_dataset),
    ),
]

#: Registered detectors with no benchmark scenario, and the reason. Every entry is a
#: commitment, not a shrug: an unmeasured detector has unknown error rates, so this list is
#: meant to stay empty. It exists so that the *reason* is reviewable in a diff rather than a
#: detector silently slipping out of measurement.
EXEMPT: dict[str, str] = {}


# ------------------------------------------------------------------------- the CI gate

#: Quality floors. Recall and AUC guard *sensitivity*; FPR guards the zero-false-HIGH bar.
#: Set below what the detectors actually achieve, so honest noise never reddens CI but a
#: real regression (a detector that stops firing, or starts false-alarming) does.
_MIN_RECALL = 0.90
_MAX_FPR = 0.10
_MIN_AUC = 0.85


@pytest.fixture(scope="module")
def metrics() -> dict[str, DetectorMetrics]:
    result = run_benchmark(SCENARIOS, seeds=_SEEDS)
    print("\n" + format_table(result))  # surfaces the table in CI logs
    return result


def test_every_scenario_meets_its_recall_floor(metrics: dict[str, DetectorMetrics]) -> None:
    weak = {i: m.recall for i, m in metrics.items() if m.recall < _MIN_RECALL}
    assert not weak, f"recall below {_MIN_RECALL}: {weak}"


def test_no_detector_exceeds_the_false_positive_bar(metrics: dict[str, DetectorMetrics]) -> None:
    noisy = {i: m.false_positive_rate for i, m in metrics.items() if m.false_positive_rate > _MAX_FPR}
    assert not noisy, f"false-positive rate above {_MAX_FPR}: {noisy}"


def test_confidence_separates_faulted_from_clean(metrics: dict[str, DetectorMetrics]) -> None:
    poor = {i: m.roc_auc for i, m in metrics.items() if m.roc_auc < _MIN_AUC}
    assert not poor, f"ROC-AUC below {_MIN_AUC}: {poor}"


def test_every_registered_detector_is_measured() -> None:
    """No detector ships without measured error rates.

    This is the structural half of "measured, not asserted": the previous version of this
    suite checked only that *some* detector from each of seven families had a scenario, which
    let 31 of 48 detectors — including all of VISION, LABEL, CONSISTENCY, CAUSAL and
    POLICY↔DATA — ship with unknown recall and unknown false-positive rate. Enumerating the
    registry instead means a new detector cannot be added without either a scenario or an
    explicit, reviewable entry in :data:`EXEMPT`.
    """
    registered = {d.id for d in discover_detectors()}
    measured = {s.detector.id for s in SCENARIOS}
    missing = sorted(registered - measured - set(EXEMPT))
    assert not missing, (
        f"{len(missing)} detector(s) have no measured recall/FPR: {missing}. "
        f"Add a Scenario to SCENARIOS, or an entry to EXEMPT stating why it cannot be measured."
    )


def test_the_exemption_list_stays_honest() -> None:
    """An exemption must name a real detector and give a reason."""
    registered = {d.id for d in discover_detectors()}
    for detector_id, reason in EXEMPT.items():
        assert detector_id in registered, f"EXEMPT names an unregistered detector: {detector_id}"
        assert len(reason) > 20, f"EXEMPT[{detector_id}] needs a real reason, got {reason!r}"


def test_no_scenario_targets_an_unregistered_detector() -> None:
    """A scenario for a detector nobody runs measures nothing; usually a stale rename."""
    registered = {d.id for d in discover_detectors()}
    stale = sorted({s.detector.id for s in SCENARIOS} - registered)
    assert not stale, f"scenarios target detectors that are not registered: {stale}"


def test_every_family_is_represented(metrics: dict[str, DetectorMetrics]) -> None:
    families = {i.split(".")[0] for i in metrics}
    expected = {
        "integrity",
        "stats",
        "smoothness",
        "temporal",
        "coverage",
        "consistency",
        "multimodality",
        "vision",
        "label",
        "policy_data",
        "dynamics",
        "causal",
    }
    assert expected <= families, f"unmeasured families: {sorted(expected - families)}"


def test_perfect_and_silent_detectors_are_scored_correctly() -> None:
    """A sanity check on the harness itself, via the strongest and a dataset-wide scenario."""
    m = run_scenario(SCENARIOS[0], seeds=_SEEDS)  # nan_inf: unambiguous
    assert m.recall == 1.0
    assert m.false_positive_rate == 0.0
    assert m.roc_auc == 1.0
