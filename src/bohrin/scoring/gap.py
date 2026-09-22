"""The Verification Gap.

    The distance between what the grader reports happened and what actually happened.

Reported 0-100. Low means the verifier is trustworthy; high means the reported pass rate
is substantially fiction.

The specification, the weights and this implementation are all public, because anyone
receiving a Bohrin result has to be able to recompute it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from bohrin.ir.result import ProbeResult, ProbeStatus

#: The published weight of each check in the headline. Equal weighting for the checks that
#: can be scored soundly, until there is measured evidence on which best predicts real harm —
#: inventing weights would be a claim that cannot be supported. The two checks at zero are
#: reported beside the headline and never counted in it, because a correct grader produces
#: the same result: one enforcing a documented output format refuses its own bare answer, and
#: an extractive task contains its answer in the prompt by design.
WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        "weak_oracle": 1.0,
        "determinism": 1.0,
        "ground_truth_rejected": 0.0,
        "answer_leakage": 0.0,
    }
)

#: Each check's family. ``acceptance`` and ``rejection`` are the two sides of the gap.
FAMILIES: Mapping[str, str] = MappingProxyType(
    {
        "weak_oracle": "acceptance",
        "determinism": "reliability",
        "ground_truth_rejected": "rejection",
        "answer_leakage": "task_validity",
    }
)

#: The weight of a check not named in :data:`WEIGHTS`, such as a third-party one.
DEFAULT_WEIGHT = 1.0


@dataclass(frozen=True, slots=True)
class Coverage:
    """Which checks actually contributed to a score."""

    measured: tuple[str, ...]
    total: int

    def __str__(self) -> str:
        return f"{len(self.measured)} of {self.total} {'probe' if self.total == 1 else 'probes'}"


#: The two directions a reward signal can be wrong in, as check families. Reported side by
#: side because they are different defects with different fixes, and pooling them is what the
#: literature on reward hacking warns against.
SIDES = ("acceptance", "rejection")


@dataclass(frozen=True, slots=True)
class Side:
    """One direction of the gap: how often the verifier was wrong that way.

    ``score`` is the unweighted mean of the sub-scores of this side's completed checks, 0-100,
    or ``None`` when none completed. Unweighted on purpose: a check's gap weight decides
    whether it moves the headline, and a rejection-side check is kept out of the headline for
    soundness reasons that say nothing about how it compares with other rejection-side checks.
    """

    name: str
    score: float | None
    probes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GapScore:
    """A Verification Gap, inseparable from the coverage that produced it.

    The two are one object on purpose. A gap computed from two checks and a gap computed from
    six are different quantities, and letting them share a name would destroy the metric this
    is meant to become. Rendering the score without the coverage is a bug, and ``__str__`` is
    written so that the easy path is also the correct one.
    """

    #: None when no check produced a measurement — not zero, which would read as "clean".
    score: float | None
    coverage: Coverage
    #: Acceptance and rejection sides, for each that had a check in the result set. Never part
    #: of ``score``: the headline is still the weighted mean above.
    sides: tuple[Side, ...] = ()

    def __str__(self) -> str:
        if self.score is None:
            return f"VERIFICATION GAP: not measured   coverage: {self.coverage}"
        return f"VERIFICATION GAP: {self.score:.0f} / 100   coverage: {self.coverage}"


def verification_gap(
    results: Sequence[ProbeResult],
    weights: Mapping[str, float] = WEIGHTS,
    families: Mapping[str, str] = FAMILIES,
) -> GapScore:
    """Weighted mean of the sub-scores of checks that completed, scaled to 0-100.

        VG = 100 * sum(w_i * s_i) / sum(w_i)   over checks with status OK

    Checks that errored or did not apply are excluded from **both** sums. Scoring them zero
    would report "clean" for a measurement that never happened, which is the single most
    misleading thing this metric could do.
    """
    numerator = 0.0
    denominator = 0.0
    measured: list[str] = []

    for result in results:
        if result.status is not ProbeStatus.OK or result.sub_score is None:
            continue
        weight = weights.get(result.probe_id, DEFAULT_WEIGHT)
        numerator += weight * result.sub_score
        denominator += weight
        measured.append(result.probe_id)

    coverage = Coverage(measured=tuple(sorted(measured)), total=len(results))
    sides = _sides(results, families)
    if denominator == 0.0:
        return GapScore(score=None, coverage=coverage, sides=sides)
    return GapScore(score=100.0 * numerator / denominator, coverage=coverage, sides=sides)


def _sides(results: Sequence[ProbeResult], families: Mapping[str, str]) -> tuple[Side, ...]:
    """Each side of the gap that had a check in the result set, in :data:`SIDES` order.

    A side whose checks all failed or did not apply has ``score=None`` rather than 0, for the
    same reason the headline does: an unmeasured side is not a clean one.
    """
    out: list[Side] = []
    for side in SIDES:
        ran = [r for r in results if families.get(r.probe_id) == side]
        if not ran:
            continue
        done = [r for r in ran if r.status is ProbeStatus.OK and r.sub_score is not None]
        score = 100.0 * sum(r.sub_score or 0.0 for r in done) / len(done) if done else None
        out.append(Side(name=side, score=score, probes=tuple(sorted(r.probe_id for r in done))))
    return tuple(out)


__all__ = ["DEFAULT_WEIGHT", "FAMILIES", "SIDES", "WEIGHTS", "Coverage", "GapScore", "Side", "verification_gap"]
