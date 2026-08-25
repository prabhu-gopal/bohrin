"""Corpus collection — the engine behind ``bohrin calibrate`` (docs/07 §4.3).

Turns datasets a human has vouched for into a calibration corpus: run the ordinary
ingest→canonicalize→profile pipeline over each one, ask every calibratable detector for the
non-conformity scores it *would* have gated on, and pool them per embodiment.

**Why this is a tool and not a shipped data file.** A reference band is a claim about what
healthy data looks like on a particular robot, from a particular rig, at a particular control
rate. Shipping one measured elsewhere would export somebody else's normal as your guarantee —
and a wrong reference distribution is worse than none, because the fallback is honest about
being a heuristic whereas a bad band produces confident nonsense. So bohrin ships the
collector and you own the corpus.

**The obligation this places on the user is real, and the CLI states it.** Scores from a
dataset that is *not* clean widen the band, which silently raises the bar for every later
scan — the failure mode is under-reporting, which is the expensive direction for a tool whose
job is catching defects. ``bohrin calibrate`` therefore scans each input first and refuses to
collect from a dataset that itself trips HIGH findings unless ``--force`` is passed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from bohrin._arrays import FloatArray
from bohrin.calibrate.corpus import MIN_REFERENCE, CalibrationCorpus, CorpusBuilder
from bohrin.config import ScanConfig
from bohrin.detectors.registry import discover as discover_detectors
from bohrin.ir.schema import Severity


@dataclass(frozen=True, slots=True)
class DatasetContribution:
    """What one known-good dataset contributed to the corpus."""

    path: str
    embodiment: str | None
    n_episodes: int
    #: ``detector_id → number of reference scores contributed``.
    bands: dict[str, int] = field(default_factory=dict)
    #: Detector ids that reported HIGH on this dataset — a reason to doubt it is clean.
    high_findings: tuple[str, ...] = ()

    @property
    def is_clean(self) -> bool:
        """Whether the dataset passed its own scan without a HIGH finding."""
        return not self.high_findings


@dataclass(frozen=True, slots=True)
class CollectionResult:
    """The corpus plus a per-dataset account of where its numbers came from."""

    corpus: CalibrationCorpus
    contributions: tuple[DatasetContribution, ...]
    skipped: tuple[DatasetContribution, ...] = ()

    def usable_bands(self) -> dict[str, int]:
        """Bands that clear :data:`MIN_REFERENCE` — the ones that will actually be used."""
        return {key: n for key, n in self.corpus.coverage().items() if n >= MIN_REFERENCE}

    def undersized_bands(self) -> dict[str, int]:
        """Bands too small to support a bound; these stay on the robust-z fallback."""
        return {key: n for key, n in self.corpus.coverage().items() if n < MIN_REFERENCE}


def collect_scores(config: ScanConfig) -> tuple[str | None, dict[str, FloatArray], int]:
    """Score one dataset: ``(embodiment, {detector_id: scores}, n_episodes)``.

    Only detectors that are *applicable* to this dataset and that implement
    :meth:`~bohrin.detectors.base.Detector.score_units` contribute — the same applicability
    gate a scan uses, so a corpus never contains scores from a detector that would not have
    run anyway.
    """
    from bohrin.engine import prepare_scan  # local: engine imports this package's siblings

    prepared = prepare_scan(config)
    ctx = prepared.ctx
    scores: dict[str, FloatArray] = {}
    for detector in discover_detectors():
        if not detector.applicable(ctx.profile, ctx.policy):
            continue
        units = detector.score_units(ctx)
        if units is None or units.size == 0:
            continue
        scores[detector.id] = units
    return ctx.schema.embodiment, scores, ctx.profile.n_episodes


def build_corpus(
    paths: Sequence[str],
    *,
    base: ScanConfig | None = None,
    force: bool = False,
) -> CollectionResult:
    """Collect a corpus from ``paths``, which must be datasets known to be good.

    Unless ``force`` is set, a dataset whose own scan reports a HIGH finding is *skipped*:
    calibrating on defective data teaches the gate that the defect is normal.
    """
    from bohrin.engine import run_scan

    builder = CorpusBuilder()
    contributions: list[DatasetContribution] = []
    skipped: list[DatasetContribution] = []
    for path in paths:
        config = (base or ScanConfig(path=path)).with_overrides(path=path)
        report = run_scan(config)
        highs = tuple(
            sorted({f.detector_id for c in report.clusters for f in c.findings if f.severity is Severity.HIGH})
        )
        embodiment, scores, n_episodes = collect_scores(config)
        contribution = DatasetContribution(
            path=path,
            embodiment=embodiment,
            n_episodes=n_episodes,
            bands={detector_id: int(values.size) for detector_id, values in sorted(scores.items())},
            high_findings=highs,
        )
        if highs and not force:
            skipped.append(contribution)
            continue
        for detector_id, values in scores.items():
            builder.add(embodiment, detector_id, values)
        contributions.append(contribution)
    return CollectionResult(
        corpus=builder.build(),
        contributions=tuple(contributions),
        skipped=tuple(skipped),
    )
