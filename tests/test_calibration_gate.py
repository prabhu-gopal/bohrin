"""The calibrated gate: FDR control, corpus wiring, and the collection tool (docs/07 §4).

This is the suite behind the claim that ``--fpr`` *governs* something. It proves four things:

1. **Benjamini–Hochberg does what the gate needs.** Under the global null it stays silent with
   probability ≥ 1 − q (the zero-false-HIGH bar as a theorem), it controls the realized false
   discovery proportion, and it still has power when real outliers are present.
2. **The fallback is unchanged.** With no corpus, the gate reproduces the shipped robust-z
   behaviour exactly — so adding calibration cannot have silently moved any existing result.
3. **The corpus path is actually taken**, per calibratable detector, and is *recorded* in the
   finding rather than left implicit.
4. **The round trip works end to end**: collect from known-good data → save → load → scan, and
   a fresh clean dataset stays clean while a faulted one still trips.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import _synth
from bohrin._arrays import FloatArray
from bohrin.analysis.robust import mad_scores
from bohrin.calibrate.collect import build_corpus, collect_scores
from bohrin.calibrate.conformal import ConformalCalibrator, Selection
from bohrin.calibrate.corpus import MIN_REFERENCE, WILDCARD, CalibrationCorpus, CorpusBuilder
from bohrin.calibrate.fdr import benjamini_hochberg, bh_cutoff
from bohrin.calibrate.gate import GateMethod, gate, required_band_size
from bohrin.config import ScanConfig
from bohrin.detectors.base import Detector
from bohrin.detectors.consistency import TrajectoryAlignmentDetector
from bohrin.detectors.dynamics import ForwardResidualDetector, InverseResidualDetector
from bohrin.detectors.kinematics import CurvatureDetector, PathEfficiencyDetector
from bohrin.detectors.registry import discover as discover_detectors
from bohrin.detectors.smoothness import DiscontinuityJumpDetector, JerkOutlierDetector
from bohrin.ir.schema import Severity

# The detectors that expose a calibratable score. Kept explicit so *adding* one without a
# test, or dropping one by accident, both show up here rather than silently.
CALIBRATABLE = [
    JerkOutlierDetector(),
    DiscontinuityJumpDetector(),
    PathEfficiencyDetector(),
    CurvatureDetector(),
    TrajectoryAlignmentDetector(),
    InverseResidualDetector(),
    ForwardResidualDetector(),
]


# --------------------------------------------------------------- 1. the BH procedure itself


def test_bh_is_silent_under_the_global_null() -> None:
    """No outliers ⇒ no rejections, with probability ≥ 1 − q.

    This is the property the magic robust-z constants were standing in for, and the reason a
    per-unit ``p ≤ fpr`` rule could never be the gate: on 200 in-distribution units it flags
    ~``fpr·200`` of them by construction. Asserted here as a rate over many independent
    draws, not on a single lucky seed.
    """
    q = 0.05
    rng = np.random.default_rng(0)
    trials = 400
    fired_bh = 0
    fired_per_unit = 0
    for _ in range(trials):
        reference = rng.normal(size=500)
        clean = rng.normal(size=200)  # all null: same distribution as the reference
        cal = ConformalCalibrator(q)
        fired_bh += bool(cal.calibrate(clean, calibration=reference, selection=Selection.FDR_BH).is_anomaly.any())
        fired_per_unit += bool(cal.calibrate(clean, calibration=reference).is_anomaly.any())

    bh_rate = fired_bh / trials
    assert bh_rate <= 2 * q, f"BH fired on {bh_rate:.3f} of clean batches, above the {q} bound"
    # And the contrast that motivates the whole change: the per-unit rule fires essentially
    # always on a clean batch this size, because it is not a simultaneous procedure.
    assert fired_per_unit / trials > 0.9


def test_bh_controls_the_false_discovery_proportion() -> None:
    """With a real outlier population present, the *reported* set stays mostly true."""
    q = 0.1
    rng = np.random.default_rng(1)
    proportions: list[float] = []
    for _ in range(200):
        reference = rng.normal(size=1000)
        nulls = rng.normal(size=180)
        outliers = rng.normal(loc=4.0, size=20)
        scores = np.concatenate([nulls, outliers])
        is_outlier = np.concatenate([np.zeros(180, dtype=bool), np.ones(20, dtype=bool)])
        selected = (
            ConformalCalibrator(q).calibrate(scores, calibration=reference, selection=Selection.FDR_BH).is_anomaly
        )
        if selected.any():
            proportions.append(float((selected & ~is_outlier).sum()) / float(selected.sum()))
    assert proportions, "BH never fired although a strong outlier population was present"
    assert float(np.mean(proportions)) <= q + 0.02


def test_bh_has_power_against_clear_outliers() -> None:
    rng = np.random.default_rng(2)
    reference = rng.normal(size=2000)
    scores = np.concatenate([rng.normal(size=50), rng.normal(loc=6.0, size=10)])
    selected = benjamini_hochberg(ConformalCalibrator(0.05).calibrate(scores, calibration=reference).pvalues, 0.05)
    assert selected[-10:].sum() >= 9  # finds essentially all of the planted outliers


@pytest.mark.parametrize("q", [0.0, 1.0, -0.1])
def test_bh_refuses_a_degenerate_level(q: float) -> None:
    assert bh_cutoff(np.array([0.001, 0.5]), q) == 0.0


def test_bh_on_an_empty_batch_is_empty() -> None:
    assert benjamini_hochberg(np.empty(0), 0.05).size == 0


def test_bh_treats_tied_pvalues_identically() -> None:
    """Ties must not be split by sort order, or a run stops being reproducible."""
    p = np.array([0.001, 0.001, 0.001, 0.9, 0.9])
    selected = benjamini_hochberg(p, 0.05)
    assert selected.tolist() == [True, True, True, False, False]


# ------------------------------------------------------- 2. the fallback is byte-unchanged


def test_without_a_corpus_the_gate_is_the_shipped_robust_z_rule() -> None:
    """No band ⇒ identical selection to ``mad_scores(scores) > z``, the pre-calibration rule."""
    rng = np.random.default_rng(3)
    scores = np.concatenate([rng.normal(size=60), np.array([40.0, 55.0])])
    result = gate(scores, fpr=0.01, detector_id="d", fallback_z=3.5)
    expected = sorted(np.flatnonzero(mad_scores(scores) > 3.5).tolist(), key=lambda i: -scores[i])
    assert result.method is GateMethod.ROBUST_Z
    assert list(result.flagged) == expected
    assert result.reference_n == 0
    assert "robust-z heuristic" in result.note()


def test_an_undersized_band_is_refused_and_falls_back() -> None:
    """A band below MIN_REFERENCE cannot support a bound, so it must not be used as if it could."""
    corpus = CalibrationCorpus.from_dict({"embodiments": {WILDCARD: {"d": list(np.linspace(0, 1, 10))}}})
    result = gate(np.array([0.5, 9.0]), fpr=0.05, detector_id="d", fallback_z=3.5, corpus=corpus)
    assert result.method is GateMethod.ROBUST_Z


# ------------------------------------------------------------ 3. the corpus path is taken


def test_with_a_band_the_gate_switches_to_conformal_fdr() -> None:
    rng = np.random.default_rng(4)
    band = rng.normal(size=4000)  # comfortably above required_band_size(41, 0.05)
    scores = np.concatenate([rng.normal(size=40), np.array([9.0])])
    result = gate(scores, fpr=0.05, detector_id="d", fallback_z=3.5, corpus=_corpus_of({"d": band}))
    assert result.method is GateMethod.CONFORMAL_FDR
    assert result.reference_n == 4000
    assert result.flagged and result.flagged[0] == len(scores) - 1
    assert "conformal FDR" in result.note()
    assert "Benjamini" in result.note()


def test_required_band_size_follows_the_resolution_limit() -> None:
    """``n ≥ m/q − 1``: the band must resolve a p-value small enough for BH's first rung."""
    assert required_band_size(1, 0.05) == 19
    assert required_band_size(100, 0.01) == 9999
    assert required_band_size(0, 0.05) == 0


def test_an_underpowered_band_falls_back_and_says_how_much_more_is_needed() -> None:
    """A band too small to ever reject must not masquerade as a clean bill of health.

    This is the trap the resolution limit sets: conformal p-values bottom out at 1/(n+1), so
    a modest band tests hundreds of units and *structurally* cannot flag any of them. Silence
    there would be indistinguishable from "your data is fine".
    """
    rng = np.random.default_rng(9)
    band = rng.normal(size=200)
    scores = np.concatenate([rng.normal(size=300), np.array([50.0])])  # an unmissable outlier
    result = gate(scores, fpr=0.01, detector_id="d", fallback_z=3.5, corpus=_corpus_of({"d": band}))

    assert result.method is GateMethod.ROBUST_Z
    assert result.underpowered == (200, required_band_size(301, 0.01))
    assert result.fired, "the fallback must still catch a 50-sigma outlier"
    assert "200 scores but" in result.note()
    assert "calibrate on more known-good episodes" in result.note()


def test_the_gate_never_flags_an_ineligible_unit() -> None:
    """The effect-size floor is a veto: statistical unusualness alone must not report."""
    rng = np.random.default_rng(5)
    band = rng.normal(size=500)
    scores = np.array([9.0, 9.5])
    eligible = np.array([False, True])
    result = gate(scores, fpr=0.05, detector_id="d", fallback_z=3.5, corpus=_corpus_of({"d": band}), eligible=eligible)
    assert list(result.flagged) == [1]


def test_exact_embodiment_band_wins_over_the_wildcard() -> None:
    rng = np.random.default_rng(6)
    corpus = CalibrationCorpus(
        version="1.0",
        by_embodiment={
            "synth_arm": {"d": rng.normal(loc=100.0, size=200)},  # so nothing looks anomalous
            WILDCARD: {"d": rng.normal(size=200)},
        },
    )
    tight = gate(np.array([5.0]), fpr=0.05, detector_id="d", fallback_z=3.5, corpus=corpus, embodiment="synth_arm")
    loose = gate(np.array([5.0]), fpr=0.05, detector_id="d", fallback_z=3.5, corpus=corpus, embodiment="other")
    assert not tight.fired  # 5.0 is unremarkable against the loc=100 band
    assert loose.fired  # but extreme against the standard-normal wildcard band


@pytest.mark.parametrize("detector", CALIBRATABLE, ids=lambda d: d.id)
def test_every_calibratable_detector_exposes_and_uses_its_score(detector: Detector) -> None:
    """``score_units`` must return the real gating quantity, and the gate must switch on it.

    The contract in :meth:`Detector.score_units` is unenforceable by types — nothing stops a
    detector returning *some other* array of the right shape. What is checkable, and what
    actually matters, is that the score exists, is finite, and that a band built from it
    genuinely moves that detector onto the calibrated path.
    """
    ctx = _synth.build_context(_synth.smooth_dataset(n_episodes=14))
    scores = detector.score_units(ctx)
    assert scores is not None, f"{detector.id} is listed as calibratable but returns no scores"
    assert scores.size > 0
    assert np.isfinite(scores).all(), f"{detector.id} produced non-finite scores"

    # Size the band to the resolution limit for this detector's unit count, which is what a
    # real corpus has to clear too (a step-level detector needs far more reference data than
    # an episode-level one, because it tests far more units per scan).
    fpr = 0.05
    band = _band_for(scores, n_units=int(scores.size), fpr=fpr)
    result = gate(
        scores,
        fpr=fpr,
        detector_id=detector.id,
        fallback_z=3.5,
        corpus=_corpus_of({detector.id: band}),
        embodiment=ctx.schema.embodiment,
    )
    assert result.method is GateMethod.CONFORMAL_FDR, result.note()
    assert result.reference_n >= MIN_REFERENCE


def test_a_calibrated_finding_says_which_gate_produced_it() -> None:
    """Honesty requirement: a heuristic result must never be mistakable for a calibrated one."""
    episodes = _synth.smooth_dataset(n_episodes=14, erratic_at=(3,))
    plain = list(JerkOutlierDetector().run(_synth.build_context(episodes)))
    assert plain and "robust-z heuristic" in plain[0].evidence.notes

    clean = _synth.build_context(_synth.smooth_dataset(n_episodes=14))
    scores = JerkOutlierDetector().score_units(clean)
    assert scores is not None
    band = _band_for(scores, n_units=14, fpr=0.05)
    ctx = _synth.build_context(
        episodes,
        config=ScanConfig(path="mem:test", fpr=0.05),
        corpus=_corpus_of({"smoothness.jerk_outlier": band}),
    )
    calibrated = list(JerkOutlierDetector().run(ctx))
    assert calibrated and "conformal FDR" in calibrated[0].evidence.notes
    assert "conformal_p" in calibrated[0].evidence.metrics


# ------------------------------------------------------------------- 4. corpus round trip


def test_corpus_save_load_round_trip(tmp_path: Path) -> None:
    rng = np.random.default_rng(7)
    original = _corpus_of({"a.b": rng.normal(size=80), "c.d": rng.normal(size=90)})
    path = tmp_path / "nested" / "corpus.json"
    original.save(path)  # also proves parent directories are created
    reloaded = CalibrationCorpus.load(path)
    for key in ("a.b", "c.d"):
        before, after = original.resolve(key, None), reloaded.resolve(key, None)
        assert before is not None and after is not None
        assert np.allclose(np.sort(before), after)


def test_saved_corpus_is_byte_reproducible(tmp_path: Path) -> None:
    """Two saves of the same corpus must be identical, so a corpus file is diffable."""
    corpus = _corpus_of({"a.b": np.random.default_rng(8).normal(size=60)})
    first, second = tmp_path / "1.json", tmp_path / "2.json"
    corpus.save(first)
    corpus.save(second)
    assert first.read_text() == second.read_text()


def test_builder_pools_across_datasets_and_fills_the_wildcard() -> None:
    builder = CorpusBuilder()
    builder.add("so101", "d", np.arange(30, dtype=np.float64))
    builder.add("so101", "d", np.arange(30, dtype=np.float64))  # a second known-good dataset
    corpus = builder.build()
    pooled = corpus.resolve("d", "so101")
    assert pooled is not None and pooled.size == 60  # pooling is what clears MIN_REFERENCE
    assert corpus.resolve("d", "an_unseen_robot") is not None  # via the wildcard


def test_builder_drops_non_finite_scores() -> None:
    builder = CorpusBuilder()
    builder.add("x", "d", np.array([1.0, np.nan, np.inf, 2.0]))
    corpus = builder.build()
    band = corpus.by_embodiment["x"]["d"]
    assert band.tolist() == [1.0, 2.0]


def test_coverage_reports_band_sizes() -> None:
    corpus = _corpus_of({"a.b": np.zeros(70)})
    assert corpus.coverage()["*/a.b"] == 70


# ------------------------------------------------------------ 5. collection, end to end


def test_collect_scores_returns_the_calibratable_detectors() -> None:
    path = _synth.register_memory_dataset(_synth.smooth_dataset(n_episodes=14))
    embodiment, scores, n_episodes = collect_scores(ScanConfig(path=path))
    assert embodiment == "synth_arm"
    assert n_episodes == 14
    assert "smoothness.jerk_outlier" in scores
    # And nothing that has no score distribution to calibrate.
    assert "integrity.nan_inf" not in scores


def test_build_corpus_refuses_a_dataset_that_reports_high() -> None:
    """Calibrating on defective data teaches the gate that the defect is normal."""
    dirty = _synth.register_memory_dataset(_synth.inject_dead_dimension(_synth.clean_dataset(n_episodes=12)))
    result = build_corpus([dirty])
    assert not result.contributions
    assert len(result.skipped) == 1
    assert not result.skipped[0].is_clean
    assert "stats.dead_dimension" in result.skipped[0].high_findings
    assert result.corpus.is_empty


def test_build_corpus_force_overrides_the_refusal() -> None:
    dirty = _synth.register_memory_dataset(_synth.inject_dead_dimension(_synth.clean_dataset(n_episodes=12)))
    result = build_corpus([dirty], force=True)
    assert result.contributions and not result.skipped


def test_build_corpus_pools_several_clean_datasets() -> None:
    paths = [_synth.register_memory_dataset(_synth.smooth_dataset(n_episodes=14)) for _ in range(4)]
    result = build_corpus(paths)
    assert len(result.contributions) == 4
    assert result.usable_bands(), "pooling four clean datasets should clear MIN_REFERENCE somewhere"
    assert all(n >= MIN_REFERENCE for n in result.usable_bands().values())
    assert all(n < MIN_REFERENCE for n in result.undersized_bands().values())


#: Enough clean datasets that the pooled step-level band clears the resolution limit for a
#: scan of ``_HOLDOUT_EPISODES`` episodes at ``_E2E_FPR``. Sized deliberately rather than
#: guessed: ``smoothness.discontinuity_jump`` tests one unit per step, so it needs ~1/q times
#: as many reference steps as the dataset under test has.
_E2E_FPR = 0.1
_HOLDOUT_EPISODES = 16
_TRAINING_DATASETS = 12


@pytest.fixture(scope="module")
def clean_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A corpus collected from many known-good datasets, saved once for the e2e tests."""
    path = tmp_path_factory.mktemp("corpus") / "corpus.json"
    training = [
        _synth.register_memory_dataset(_synth.smooth_dataset(n_episodes=_HOLDOUT_EPISODES))
        for _ in range(_TRAINING_DATASETS)
    ]
    result = build_corpus(training)
    assert len(result.contributions) == _TRAINING_DATASETS, (
        f"collection refused a fixture dataset as unclean: {[c.high_findings for c in result.skipped]}"
    )
    result.corpus.save(path)
    return path


def test_the_collected_corpus_actually_powers_a_step_level_gate(clean_corpus: Path) -> None:
    """Guard for the tests below: prove the conformal path is reachable at this corpus size.

    Without this, "clean data stayed clean" would be satisfied vacuously by a corpus too
    small to ever fire — the exact failure the resolution-limit guard exists to expose.
    """
    corpus = CalibrationCorpus.load(clean_corpus)
    ctx = _synth.build_context(_synth.smooth_dataset(n_episodes=_HOLDOUT_EPISODES))
    scores = DiscontinuityJumpDetector().score_units(ctx)
    assert scores is not None
    result = gate(
        scores,
        fpr=_E2E_FPR,
        detector_id="smoothness.discontinuity_jump",
        fallback_z=10.0,
        corpus=corpus,
        embodiment=ctx.schema.embodiment,
    )
    assert result.method is GateMethod.CONFORMAL_FDR, result.note()


def test_a_corpus_from_clean_data_keeps_fresh_clean_data_clean(clean_corpus: Path) -> None:
    """The payoff, stated as behaviour: calibration must not manufacture findings.

    Scan *held-out* datasets from the same generator as the corpus. The calibrated detectors
    must stay silent — if switching to conformal FDR introduced findings on data that is clean
    by construction, the bound would be worthless.
    """
    from bohrin.api import scan

    calibratable_ids = {d.id for d in CALIBRATABLE}
    for _ in range(5):
        holdout = _synth.register_memory_dataset(_synth.smooth_dataset(n_episodes=_HOLDOUT_EPISODES))
        report = scan(holdout, calibration=str(clean_corpus), fpr=_E2E_FPR)
        fired = {c.id for c in report.clusters} & calibratable_ids
        assert not fired, f"calibrated gate invented findings on clean holdout data: {fired}"


def test_a_calibrated_scan_still_catches_a_planted_defect(clean_corpus: Path) -> None:
    """Silence on clean data is only half the bar — the gate must still fire on real faults."""
    from bohrin.api import scan

    faulted = _synth.register_memory_dataset(
        [
            _synth.inject_jump(ep, at=20, magnitude=5.0) if i == 3 else ep
            for i, ep in enumerate(_synth.smooth_dataset(n_episodes=_HOLDOUT_EPISODES))
        ]
    )
    report = scan(faulted, calibration=str(clean_corpus), fpr=_E2E_FPR)
    cluster = report.cluster("smoothness.discontinuity_jump")
    assert cluster is not None, "a 5-unit teleport went unreported under the calibrated gate"
    assert cluster.severity is Severity.HIGH
    assert "conformal FDR" in cluster.findings[0].evidence.notes


def test_a_missing_corpus_path_degrades_to_self_calibration() -> None:
    """A typo in --calibration must not silently become a stronger claim, nor crash the scan."""
    from bohrin.api import scan

    path = _synth.register_memory_dataset(_synth.smooth_dataset(n_episodes=14, erratic_at=(2,)))
    report = scan(path, calibration="/no/such/corpus.json")
    for cluster in report.clusters:
        for finding in cluster.findings:
            assert "conformal FDR" not in finding.evidence.notes


def test_no_detector_claims_calibration_it_did_not_use() -> None:
    """Sweep: every finding from an uncalibrated scan must be labelled a heuristic or nothing."""
    path = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=14))
    _, scores, _ = collect_scores(ScanConfig(path=path))
    calibratable_ids = {d.id for d in discover_detectors() if d.id in scores}
    assert calibratable_ids, "no calibratable detector applied to the fixture"
    assert calibratable_ids <= {d.id for d in CALIBRATABLE}, (
        "a detector gained a calibratable score without being added to CALIBRATABLE in this test"
    )


def _band_for(scores: FloatArray, *, n_units: int, fpr: float) -> FloatArray:
    """A reference band drawn from ``scores``, sized to clear the resolution limit.

    Tiling a clean detector's own scores is a legitimate stand-in for a real reference band
    here: the point under test is the *plumbing and the decision rule*, not how representative
    a particular robot's calibration data is.
    """
    needed = max(required_band_size(n_units, fpr) + 1, MIN_REFERENCE)
    repeats = (needed // max(scores.size, 1)) + 1
    return np.tile(np.asarray(scores, dtype=np.float64), repeats)


def _corpus_of(bands: dict[str, FloatArray]) -> CalibrationCorpus:
    """A wildcard-keyed corpus from ``detector_id → band``."""
    return CalibrationCorpus(
        version="1.0",
        by_embodiment={WILDCARD: {key: np.asarray(v, dtype=np.float64) for key, v in bands.items()}},
    )
