"""The Coverage Score, from both directions.

A correct grader must catch every category the battery could measure, and a weak one must
not be scored as if it had. Leads never count, a task-and-category pair is caught only when
every grounded candidate in it was rejected, and a score over nothing is not 100.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence

from _fixtures import REFERENCE, task, text
from bohrin.ir.task import Candidate, Ground, Provenance, Source, Task
from bohrin.mutate import discover
from bohrin.mutate.base import MutationOperator
from bohrin.mutate.battery import battery
from bohrin.scoring.coverage import (
    BATTERY_VERSION,
    CATEGORIES,
    OTHER,
    Attempt,
    category_of,
    coverage_score,
)
from bohrin.spec.weaknesses import weakness_list


def _attempts(
    tasks: Sequence[Task], accepts: Callable[[Task, str], bool], operators: Sequence[MutationOperator] | None = None
) -> list[Attempt]:
    return [Attempt(t.id, c, accepts(t, text(c))) for t in tasks for c in battery(t, operators).candidates]


def _exact(t: Task, reply: str) -> bool:
    return reply.strip() == (t.reference or "").strip()


_ADD = "def add(a, b):\n    return a + b\n"
_TASKS = [task(REFERENCE, task_id="a"), task(_ADD, task_id="b")]


class _Hollow(MutationOperator):
    """Two hollow programs for one task, so a grader can catch one and pay for the other."""

    id = "hollow"
    category = "hollow_program"
    rationale = "test double"

    def apply(self, task: Task) -> Iterator[Candidate]:
        for body in ("return None", "raise NotImplementedError"):
            payload = f"def solve(items):\n    {body}\n"
            yield Candidate(Source(payload), Provenance(self.id, "reference", body), Ground.STRUCTURAL)


def test_every_category_is_a_weakness_family() -> None:
    """A category is a family of the weakness list, so a score reads in the list's vocabulary."""
    assert set(CATEGORIES) <= set(weakness_list().families)


def test_every_built_in_operator_declares_a_published_category() -> None:
    for op in discover():
        assert op.category in CATEGORIES, f"{op.id} counts towards no published category"


def test_a_correct_grader_catches_everything_it_was_measured_on() -> None:
    result = coverage_score(_attempts(_TASKS, _exact))

    assert result.score == 100.0
    assert result.caught == result.measured == 2
    assert [c.category for c in result.categories] == ["hollow_program"]


def test_a_grader_accepting_anything_catches_nothing() -> None:
    result = coverage_score(_attempts(_TASKS, lambda _t, reply: True))

    assert result.score == 0.0
    assert result.caught == 0


def test_one_accepted_candidate_is_enough_for_a_category_to_get_through() -> None:
    """Rejecting one hollow program and paying for the other has not caught hollow programs."""

    def pays_for_one(t: Task, reply: str) -> bool:
        # It is the first candidate tried, not the last, so a score that kept only the latest
        # attempt per category would wrongly call the category caught.
        return _exact(t, reply) or "return None" in reply

    op = _Hollow()
    result = coverage_score(_attempts([task(REFERENCE)], pays_for_one, [op]), [op])
    (hollow,) = result.categories

    assert (hollow.category, hollow.caught, hollow.measured) == ("hollow_program", 0, 1)


def test_leads_never_count_in_either_direction() -> None:
    lead = Candidate(Source("def solve(items):\n    return -1\n"), Provenance("x", "reference", "unproven"), None)
    assert coverage_score([Attempt("a", lead, accepted=True)]).score is None


def test_nothing_tried_is_not_measured_rather_than_perfect() -> None:
    result = coverage_score([])

    assert result.score is None
    assert result.measured == 0
    assert "not measured" in str(result)


def test_the_score_always_states_its_categories_battery_and_interval() -> None:
    rendered = str(coverage_score(_attempts(_TASKS, _exact)))

    assert "COVERAGE SCORE: 100 / 100" in rendered
    assert "95% CI" in rendered
    assert f"categories: 1 of {len(CATEGORIES)}" in rendered, "the categories not measured are counted, not hidden"
    assert f"battery {BATTERY_VERSION}" in rendered


def test_each_category_carries_its_own_sample_and_interval() -> None:
    for result in coverage_score(_attempts(_TASKS, _exact)).categories:
        assert result.measured > 0
        assert result.interval_95 is not None


class _Uncategorised(MutationOperator):
    id = "third_party"
    rationale = "test double"

    def apply(self, task: Task) -> Iterator[Candidate]:
        yield Candidate(Source("banana"), Provenance(self.id, "constant", "not 70"), Ground.DIFFERENTIAL)


def test_an_operator_without_a_category_counts_as_other() -> None:
    op = _Uncategorised()
    t = task("70")
    attempts = [Attempt(t.id, c, accepted=False) for c in battery(t, [op]).candidates]
    result = coverage_score(attempts, [op])

    assert [c.category for c in result.categories] == [OTHER]
    assert category_of("third_party", [op]) == OTHER
    assert "categories: 0 of" in str(result), "a category outside the published set is not claimed as covered"


def test_category_of_names_the_built_in_category() -> None:
    assert category_of("drop_side_effect") == "hollow_program"
