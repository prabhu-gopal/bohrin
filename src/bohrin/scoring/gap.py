"""The Verification Gap.

    The distance between what the grader reports happened and what actually happened.

Reported 0-100. Low means the verifier is trustworthy; high means the reported pass rate
is substantially fiction.

The specification, the weights and this implementation are all public, because anyone
receiving a Bohrin result — including a lab handed a certificate — has to be able to
recompute it. No accrediting body exists for this domain, so reproducible methodology is
the only available substitute for one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from bohrin.probes.base import Probe, ProbeResult, ProbeStatus


@dataclass(frozen=True, slots=True)
class Coverage:
    """Which probes actually contributed to a score."""

    measured: tuple[str, ...]
    total: int

    def __str__(self) -> str:
        return f"{len(self.measured)} of {self.total} {'probe' if self.total == 1 else 'probes'}"


#: The two directions a reward signal can be wrong in, as probe families. Reported side by
#: side because they are different defects with different fixes, and pooling them is what the
#: literature on reward hacking warns against.
SIDES = ("acceptance", "rejection")


@dataclass(frozen=True, slots=True)
class Side:
    """One direction of the gap: how often the verifier was wrong that way.

    ``score`` is the unweighted mean of the sub-scores of this side's completed probes, 0-100,
    or ``None`` when none completed. Unweighted on purpose: a probe's gap weight decides whether
    it moves the headline, and a rejection-side probe is kept out of the headline for soundness
    reasons that say nothing about how it compares with other rejection-side probes.
    """

    name: str
    score: float | None
    probes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GapScore:
    """A Verification Gap, inseparable from the coverage that produced it.

    The two are one object on purpose. A gap computed from two probes and a gap computed
    from six are different quantities, and letting them share a name would destroy the
    metric this is meant to become. Rendering the score without the coverage is a bug, and
    ``__str__`` is written so that the easy path is also the correct one.
    """

    #: None when no probe produced a measurement — not zero, which would read as "clean".
    score: float | None
    coverage: Coverage
    #: Acceptance and rejection sides, for each that had a probe in the audit. Never part of
    #: ``score``: the headline is still the weighted mean above.
    sides: tuple[Side, ...] = ()

    def __str__(self) -> str:
        if self.score is None:
            return f"VERIFICATION GAP: not measured   coverage: {self.coverage}"
        return f"VERIFICATION GAP: {self.score:.0f} / 100   coverage: {self.coverage}"


def verification_gap(results: Sequence[ProbeResult], probes: Sequence[Probe]) -> GapScore:
    """Weighted mean of the sub-scores of probes that completed, scaled to 0-100.

        VG = 100 * sum(w_i * s_i) / sum(w_i)   over probes with status OK

    Probes that errored or did not apply are excluded from **both** sums. Scoring them
    zero would report "clean" for a measurement that never happened, which is the single
    most misleading thing this metric could do.
    """
    weights = {p.id: p.weight for p in probes}

    numerator = 0.0
    denominator = 0.0
    measured: list[str] = []

    for result in results:
        if result.status is not ProbeStatus.OK or result.sub_score is None:
            continue
        weight = weights.get(result.probe_id, 1.0)
        numerator += weight * result.sub_score
        denominator += weight
        measured.append(result.probe_id)

    coverage = Coverage(measured=tuple(sorted(measured)), total=len(results))
    sides = _sides(results, probes)
    if denominator == 0.0:
        return GapScore(score=None, coverage=coverage, sides=sides)
    return GapScore(score=100.0 * numerator / denominator, coverage=coverage, sides=sides)


def _sides(results: Sequence[ProbeResult], probes: Sequence[Probe]) -> tuple[Side, ...]:
    """Each side of the gap that had a probe in the audit, in :data:`SIDES` order.

    A side whose probes all failed or did not apply has ``score=None`` rather than 0, for the
    same reason the headline does: an unmeasured side is not a clean one.
    """
    family = {p.id: p.family for p in probes}
    out: list[Side] = []
    for side in SIDES:
        ran = [r for r in results if family.get(r.probe_id) == side]
        if not ran:
            continue
        done = [r for r in ran if r.status is ProbeStatus.OK and r.sub_score is not None]
        score = 100.0 * sum(r.sub_score or 0.0 for r in done) / len(done) if done else None
        out.append(Side(name=side, score=score, probes=tuple(sorted(r.probe_id for r in done))))
    return tuple(out)


__all__ = ["SIDES", "Coverage", "GapScore", "Side", "verification_gap"]
