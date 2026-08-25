"""The benchmark harness — precision/recall/ROC per detector (docs/06 P4, docs/08 §4).

A detector is only as trustworthy as its measured error rates. This harness measures them
directly: give it, per detector, a way to build a **clean** context (must stay silent) and a
**faulted** one (must fire), and it runs both across many seeds and reports:

* **recall** — of the faulted trials, how often the detector fired (caught the defect).
* **precision** — of all the trials it fired on, how often a defect was actually present.
* **F1** — their harmonic mean, the single number CI gates on.
* **ROC-AUC** — how separable the fired-vs-silent decision is when ranked by the finding's
  own ``confidence``, computed as the Mann–Whitney statistic. AUC = 1.0 means confidence
  perfectly orders faulted above clean; 0.5 means no better than chance.

The harness is generic and dependency-light on purpose: it knows nothing about *which*
detectors or fixtures exist, so the scenarios (which pull the test-only synthetic data) and
the CI thresholds live in the test suite. This module just does the counting, correctly.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from bohrin.detectors.base import AnalysisContext, Detector

#: A factory takes a seed and returns a context. Seeding is explicit so a run is
#: reproducible and every detector sees an independent draw per trial.
ContextFactory = Callable[[int], AnalysisContext]


@dataclass(frozen=True, slots=True)
class Trial:
    """One measured run: whether the detector fired, and its peak confidence."""

    fired: bool
    confidence: float
    faulted: bool


@dataclass(frozen=True, slots=True)
class Scenario:
    """A detector paired with clean and faulted context factories (one defect class)."""

    detector: Detector
    clean: ContextFactory
    faulted: ContextFactory
    #: Human label for the defect, for the report. Defaults to the detector id.
    name: str = ""

    @property
    def label(self) -> str:
        return self.name or self.detector.id


@dataclass(frozen=True, slots=True)
class DetectorMetrics:
    """The measured error rates for one detector over ``n`` clean + ``n`` faulted trials."""

    detector_id: str
    true_positive: int
    false_negative: int
    false_positive: int
    true_negative: int
    roc_auc: float
    trials: list[Trial] = field(default_factory=list)

    @property
    def recall(self) -> float:
        """Caught defects ÷ present defects. 1.0 means it never misses."""
        denom = self.true_positive + self.false_negative
        return self.true_positive / denom if denom else 1.0

    @property
    def precision(self) -> float:
        """Real defects ÷ times it fired. 1.0 means it never false-alarms."""
        denom = self.true_positive + self.false_positive
        return self.true_positive / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def false_positive_rate(self) -> float:
        """The zero-false-HIGH bar in a number: fires ÷ clean trials."""
        denom = self.false_positive + self.true_negative
        return self.false_positive / denom if denom else 0.0


def _fire(detector: Detector, ctx: AnalysisContext) -> tuple[bool, float]:
    """Run a detector once; return (fired, peak confidence over its findings)."""
    findings = list(detector.run(ctx))
    if not findings:
        return False, 0.0
    return True, max(f.confidence for f in findings)


def _roc_auc(trials: Sequence[Trial]) -> float:
    """ROC-AUC via the Mann–Whitney U statistic on confidence, ranking faulted vs clean.

    AUC = P(confidence of a random faulted trial > that of a random clean trial), with ties
    counted as half. Returns 0.5 (chance) when either class is empty, so a scenario with no
    contrast never reports a misleadingly perfect score.
    """
    pos = [t.confidence for t in trials if t.faulted]
    neg = [t.confidence for t in trials if not t.faulted]
    if not pos or not neg:
        return 0.5
    wins = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(pos) * len(neg))


def run_scenario(scenario: Scenario, *, seeds: int = 20) -> DetectorMetrics:
    """Measure one detector over ``seeds`` clean and ``seeds`` faulted trials."""
    detector = scenario.detector
    trials: list[Trial] = []
    tp = fn = fp = tn = 0
    for seed in range(seeds):
        fired_c, conf_c = _fire(detector, scenario.clean(seed))
        trials.append(Trial(fired=fired_c, confidence=conf_c, faulted=False))
        if fired_c:
            fp += 1
        else:
            tn += 1

        fired_f, conf_f = _fire(detector, scenario.faulted(seed))
        trials.append(Trial(fired=fired_f, confidence=conf_f, faulted=True))
        if fired_f:
            tp += 1
        else:
            fn += 1

    return DetectorMetrics(
        detector_id=detector.id,
        true_positive=tp,
        false_negative=fn,
        false_positive=fp,
        true_negative=tn,
        roc_auc=_roc_auc(trials),
        trials=trials,
    )


def run_benchmark(scenarios: Sequence[Scenario], *, seeds: int = 20) -> dict[str, DetectorMetrics]:
    """Run every scenario; return metrics keyed by detector id (report/CI-ready)."""
    return {s.detector.id: run_scenario(s, seeds=seeds) for s in scenarios}


def format_table(metrics: dict[str, DetectorMetrics]) -> str:
    """A compact fixed-width table of the measured rates — for CI logs and reports."""
    header = f"{'detector':<40} {'recall':>7} {'prec':>7} {'F1':>7} {'AUC':>7} {'FPR':>7}"
    lines = [header, "-" * len(header)]
    for detector_id in sorted(metrics):
        m = metrics[detector_id]
        lines.append(
            f"{detector_id:<40} {m.recall:>7.2f} {m.precision:>7.2f} "
            f"{m.f1:>7.2f} {m.roc_auc:>7.2f} {m.false_positive_rate:>7.2f}"
        )
    return "\n".join(lines)
