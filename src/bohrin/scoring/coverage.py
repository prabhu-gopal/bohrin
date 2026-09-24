"""The Coverage Score.

    Of the known ways this task can be passed without doing it, what fraction would this
    grader catch?

Reported 0-100. High means the grader caught what was tried; low means it paid for work that
was provably not done. It is the complement of the question the Verification Gap asks, put
where a grader's author can read it as a grade: the Gap says how often the reported pass rate
is fiction, the Coverage Score says how much of the battery the grader stood up to.

**The unit is a task and a category.** A category is one family of ways of passing without
doing the work, named after its family in the weakness list: a hollow program, a tampered
harness, a solution obtained rather than produced. On one task, a
category is *measured* when at least one grounded candidate of that category was tried, and
*caught* when the grader accepted none of them. One accepted candidate is enough for the
category to get through on that task: a grader that rejects three hollow programs and pays
for the fourth has not caught hollow programs.

**Only grounded candidates count.** A lead — a candidate whose wrongness could not be
established without asking the grader — says nothing about whether the grader is wrong, so
it is never counted in either direction.

**It never claims more than was tried.** The score names the categories it covered and the
battery version that defined them, and carries a Wilson interval, because ``2 of 2`` and
``300 of 300`` must never read the same. A category that was not measured is not caught; it
is absent. A score is not a safety claim: it says *these named things were tried, and this
many got through*.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from bohrin.ir.task import Candidate
from bohrin.mutate import discover
from bohrin.mutate.base import MutationOperator
from bohrin.scoring.interval import wilson_interval

#: The version of the category definitions below. It changes whenever a category is added,
#: removed or redefined, because two scores are only comparable over the same definitions.
BATTERY_VERSION = "2"

#: Every category, and the way of passing without doing the work that it names. Each is a
#: family of the weakness list (``docs/WEAKNESSES.md``) whose classes a correct grader must
#: reject; the families measured by statistics or structural risk are not categories here.
CATEGORIES: Mapping[str, str] = MappingProxyType(
    {
        "hollow_program": "code that does no work: empty or constant bodies, an early exit, spoofed equality",
        "harness_tampering": "a submission that changes what judges it: test hooks, edited tests, a written reward",
        "answer_access": "a solution obtained instead of produced: read from the environment or from history",
        "weak_tests": "a wrong program or output that the tests or the checker cannot tell from a right one",
        "grader_logic": "a failure the grader scores as success",
    }
)

#: The category of a candidate whose operator declares none, such as a third-party one.
OTHER = "other"


@dataclass(frozen=True, slots=True)
class Attempt:
    """One candidate offered to the grader, and whether the grader paid full marks for it."""

    task_id: str
    candidate: Candidate
    accepted: bool


@dataclass(frozen=True, slots=True)
class CategoryResult:
    """How one category fared across the tasks it was measured on."""

    category: str
    caught: int
    measured: int

    @property
    def interval_95(self) -> tuple[float, float] | None:
        """The Wilson 95% interval on the fraction caught."""
        return wilson_interval(self.caught, self.measured)


@dataclass(frozen=True, slots=True)
class CoverageScore:
    """A Coverage Score, inseparable from the categories and the sample that produced it."""

    #: 0-100, or None when nothing grounded was tried — not 100, which would read as "caught
    #: everything" for a grader that was never tested.
    score: float | None
    caught: int
    measured: int
    #: One entry per category that was measured, in :data:`CATEGORIES` order, then any other.
    categories: tuple[CategoryResult, ...]
    battery_version: str = BATTERY_VERSION

    @property
    def interval_95(self) -> tuple[float, float] | None:
        """The Wilson 95% interval on the fraction caught, as a fraction."""
        return wilson_interval(self.caught, self.measured)

    def __str__(self) -> str:
        known = sum(1 for c in self.categories if c.category in CATEGORIES)
        covered = f"categories: {known} of {len(CATEGORIES)} (battery {self.battery_version})"
        interval = self.interval_95
        if self.score is None or interval is None:
            return f"COVERAGE SCORE: not measured   {covered}"
        low, high = interval
        return (
            f"COVERAGE SCORE: {self.score:.0f} / 100   95% CI {low * 100:.0f}–{high * 100:.0f}   "
            f"{self.caught} of {self.measured} caught   {covered}"
        )


def category_of(operator_id: str, operators: Sequence[MutationOperator] | None = None) -> str:
    """The category an operator's candidates count towards, :data:`OTHER` when it declares none."""
    for op in operators if operators is not None else discover():
        if op.id == operator_id:
            return op.category or OTHER
    return OTHER


def coverage_score(attempts: Iterable[Attempt], operators: Sequence[MutationOperator] | None = None) -> CoverageScore:
    """The fraction of measured task-and-category pairs the grader caught, scaled to 0-100."""
    ops = list(operators) if operators is not None else discover()
    category = {op.id: op.category or OTHER for op in ops}

    got_through: dict[tuple[str, str], bool] = {}
    for attempt in attempts:
        if not attempt.candidate.known_wrong:
            continue  # a lead proves nothing about the grader, in either direction
        key = (attempt.task_id, category.get(attempt.candidate.provenance.operator, OTHER))
        got_through[key] = got_through.get(key, False) or attempt.accepted

    by_category: dict[str, list[bool]] = {}
    for (_task, cat), through in got_through.items():
        by_category.setdefault(cat, []).append(through)

    order = [*(c for c in CATEGORIES if c in by_category), *sorted(set(by_category) - set(CATEGORIES))]
    results = tuple(
        CategoryResult(category=c, caught=sum(not t for t in by_category[c]), measured=len(by_category[c]))
        for c in order
    )
    measured = sum(r.measured for r in results)
    caught = sum(r.caught for r in results)
    score = 100.0 * caught / measured if measured else None
    return CoverageScore(score=score, caught=caught, measured=measured, categories=results)


__all__ = [
    "BATTERY_VERSION",
    "CATEGORIES",
    "OTHER",
    "Attempt",
    "CategoryResult",
    "CoverageScore",
    "category_of",
    "coverage_score",
]
