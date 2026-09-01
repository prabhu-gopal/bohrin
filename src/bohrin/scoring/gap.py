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
        return f"{len(self.measured)} of {self.total} probes"


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
    if denominator == 0.0:
        return GapScore(score=None, coverage=coverage)
    return GapScore(score=100.0 * numerator / denominator, coverage=coverage)


__all__ = ["Coverage", "GapScore", "verification_gap"]
