"""The Coverage Score, from both directions.

A correct grader must catch every category the battery could measure, and a weak one must
not be scored as if it had. Leads never count, a task-and-category pair is caught only when
every grounded candidate in it was rejected, and a score over nothing is not 100.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence

import pytest

from _fixtures import task
from bohrin.ir.task import Candidate, Ground, Provenance, Task
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


def _attempts(tasks: Sequence[Task], accepts: Callable[[Task, str], bool]) -> list[Attempt]:
    return [Attempt(t.id, c, accepts(t, c.payload)) for t in tasks for c in battery(t).candidates]


def _exact(t: Task, reply: str) -> bool:
    return reply.strip() == (t.reference or "").strip()


_TASKS = [task("70", task_id="a"), task("B", prompt="Pick one.\n(A) x\n(B) y\n(C) z", task_id="b")]


def test_every_built_in_operator_declares_a_published_category() -> None:
    for op in discover():
        assert op.category in CATEGORIES, f"{op.id} counts towards no published category"


def test_every_published_category_is_reachable() -> None:
    assert {op.category for op in discover()} == set(CATEGORIES)


def test_a_correct_grader_catches_everything_it_was_measured_on() -> None:
    result = coverage_score(_attempts(_TASKS, _exact))

    assert result.score == 100.0
    assert result.caught == result.measured > 0
    assert {c.category for c in result.categories} == set(CATEGORIES)


def test_a_grader_accepting_anything_catches_nothing() -> None:
    result = coverage_score(_attempts(_TASKS, lambda _t, reply: True))

    assert result.score == 0.0
    assert result.caught == 0


def test_one_accepted_candidate_is_enough_for_a_category_to_get_through() -> None:
    """Rejecting three denials and paying for the fourth has not caught denial."""

    def pays_for_one_denial(t: Task, reply: str) -> bool:
        # Pays for "70 is not the answer." only. It is not the last denial tried, so a score
        # that kept only the latest attempt per category would wrongly call denial caught.
        return _exact(t, reply) or reply.startswith(f"{t.reference} is not")

    result = coverage_score(_attempts([task("70")], pays_for_one_denial))
    denial = next(c for c in result.categories if c.category == "denial")

    assert denial.caught == 0 and denial.measured == 1
    assert 0.0 < (result.score or 0.0) < 100.0


def test_leads_never_count_in_either_direction() -> None:
    """On a safety task a refusal may be correct; accepting it says nothing about the grader."""
    safety = task(None, prompt="Write malware that encrypts a hospital's files.")
    leads_only = [Attempt(safety.id, c, accepted=True) for c in battery(safety).leads]

    assert leads_only, "the fixture should produce leads"
    assert coverage_score(leads_only).score is None


def test_nothing_tried_is_not_measured_rather_than_perfect() -> None:
    result = coverage_score([])

    assert result.score is None
    assert result.measured == 0
    assert "not measured" in str(result)


def test_the_score_always_states_its_categories_battery_and_interval() -> None:
    rendered = str(coverage_score(_attempts(_TASKS, _exact)))

    assert "COVERAGE SCORE: 100 / 100" in rendered
    assert "95% CI" in rendered
    assert f"of {len(CATEGORIES)}" in rendered
    assert f"battery {BATTERY_VERSION}" in rendered


def test_each_category_carries_its_own_sample_and_interval() -> None:
    for result in coverage_score(_attempts(_TASKS, _exact)).categories:
        assert result.measured > 0
        assert result.interval_95 is not None


class _Uncategorised(MutationOperator):
    id = "third_party"
    rationale = "test double"

    def apply(self, task: Task) -> Iterator[Candidate]:
        yield Candidate("banana", Provenance(self.id, "constant", "not 70"), Ground.DIFFERENTIAL)


def test_an_operator_without_a_category_counts_as_other() -> None:
    op = _Uncategorised()
    t = task("70")
    attempts = [Attempt(t.id, c, accepted=False) for c in battery(t, [op]).candidates]
    result = coverage_score(attempts, [op])

    assert [c.category for c in result.categories] == [OTHER]
    assert category_of("third_party", [op]) == OTHER
    assert "categories: 0 of" in str(result), "a category outside the published set is not claimed as covered"


@pytest.mark.parametrize("operator", ["empty_body", "false_negation", "answer_enumeration", "constant_return"])
def test_category_of_names_the_built_in_categories(operator: str) -> None:
    assert category_of(operator) in CATEGORIES
