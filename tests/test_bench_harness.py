"""Unit tests for the shipped benchmark harness (docs/06 P4).

The harness is what CI trusts to catch a quality regression, so its own arithmetic —
precision, recall, the Mann–Whitney AUC, tie handling — must be exactly right. These tests
drive it with synthetic detectors of *known* behaviour so a wrong count fails here rather
than silently miscounting real detectors.
"""

from __future__ import annotations

from collections.abc import Iterable

from bohrin.bench.harness import Scenario, Trial, _roc_auc, run_scenario
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.ir.schema import Family, Provenance, Severity
from bohrin.report.model import Finding, Fix


class _Stub(Detector):
    """A detector whose firing and confidence are dictated by the context's episode count.

    We smuggle the desired behaviour through the number of episodes in the context, which
    the factories below control — so one stub can play 'always fires', 'never fires', or
    'fires only when faulted'.
    """

    family = Family.STATS

    def __init__(self, detector_id: str, fire_when_episodes: int, confidence: float) -> None:
        self.id = detector_id
        self._fire_when = fire_when_episodes
        self._confidence = confidence

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        if ctx.profile.n_episodes == self._fire_when:
            yield Finding(
                detector_id=self.id,
                family=self.family,
                severity=Severity.HIGH,
                confidence=self._confidence,
                title="stub",
                mechanism="stub",
                fix=Fix(text="stub"),
                provenance=Provenance(adapter="mem", uri="mem:test"),
            )


def _ctx_with(n_episodes: int) -> AnalysisContext:
    import _synth

    return _synth.build_context(_synth.clean_dataset(n_episodes=n_episodes))


def _clean_ctx(_seed: int) -> AnalysisContext:
    return _ctx_with(4)


def _faulted_ctx(_seed: int) -> AnalysisContext:
    return _ctx_with(6)


def test_perfect_detector_scores_perfectly() -> None:
    """Fires iff faulted (6 episodes), never on clean (4)."""
    scenario = Scenario(_Stub("s.perfect", fire_when_episodes=6, confidence=0.9), _clean_ctx, _faulted_ctx)
    m = run_scenario(scenario, seeds=10)
    assert (m.true_positive, m.false_negative, m.false_positive, m.true_negative) == (10, 0, 0, 10)
    assert m.recall == 1.0 and m.precision == 1.0 and m.f1 == 1.0
    assert m.false_positive_rate == 0.0
    assert m.roc_auc == 1.0


def test_silent_detector_has_zero_recall_but_no_false_positives() -> None:
    scenario = Scenario(_Stub("s.silent", fire_when_episodes=999, confidence=0.9), _clean_ctx, _faulted_ctx)
    m = run_scenario(scenario, seeds=8)
    assert m.true_positive == 0 and m.false_negative == 8
    assert m.recall == 0.0
    assert m.false_positive_rate == 0.0
    assert m.roc_auc == 0.5  # no positive scores → no separation


def test_trigger_happy_detector_has_full_recall_and_high_fpr() -> None:
    """Fires on the clean context (4 episodes), never on faulted — inverted, worst case."""
    scenario = Scenario(_Stub("s.noisy", fire_when_episodes=4, confidence=0.9), _clean_ctx, _faulted_ctx)
    m = run_scenario(scenario, seeds=8)
    assert m.false_positive == 8 and m.true_negative == 0
    assert m.false_positive_rate == 1.0
    assert m.recall == 0.0  # it fires, but never on the faulted case


def test_precision_counts_only_real_defects_among_fires() -> None:
    """A detector that fires on *both* clean and faulted: half its alarms are false."""

    class _Always(_Stub):
        def run(self, ctx: AnalysisContext) -> Iterable[Finding]:  # fires every time
            yield Finding(
                detector_id=self.id,
                family=self.family,
                severity=Severity.HIGH,
                confidence=0.9,
                title="stub",
                mechanism="stub",
                fix=Fix(text="stub"),
                provenance=Provenance(adapter="mem", uri="mem:test"),
            )

    scenario = Scenario(_Always("s.always", 0, 0.9), _clean_ctx, _faulted_ctx)
    m = run_scenario(scenario, seeds=6)
    assert m.true_positive == 6 and m.false_positive == 6  # fires on both classes
    assert m.recall == 1.0
    assert m.precision == 0.5  # only half its fires were on a real defect


def test_roc_auc_handles_ties_as_half() -> None:
    trials = [Trial(fired=True, confidence=0.5, faulted=True), Trial(fired=True, confidence=0.5, faulted=False)]
    assert _roc_auc(trials) == 0.5


def test_roc_auc_rewards_correct_ordering() -> None:
    trials = [Trial(fired=True, confidence=0.9, faulted=True), Trial(fired=False, confidence=0.0, faulted=False)]
    assert _roc_auc(trials) == 1.0


def test_requirements_default_is_available() -> None:
    """Regression guard for the P0 Requirements-as-Field bug that broke every stub detector."""
    assert isinstance(_Stub("x", 1, 0.5).requires, Requirements)
