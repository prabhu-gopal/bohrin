"""One-cell answers: ``0``, ``[0]`` and ``[[0]]`` are the same answer.

Found by reviewing a finding Bohrin had already made. A public grid-answer environment declares
the answer ``[[0]]`` on some tasks, and its parser reads space-separated digit rows as a grid --
the format its own prompts use -- so the reply ``0`` parses to ``[[0]]`` and earns full marks.
That verifier is behaving correctly, and a constant candidate ``0`` claimed to be provably
distinct from ``[[0]]`` reported it as exploited.

The ladder may only ever remove findings, so the counterweights matter most: a different
one-cell answer, and a genuinely multi-cell one, must stay distinct.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from bohrin.ir.task import Candidate, Ground, Provenance, Task
from bohrin.mutate.base import MutationOperator
from bohrin.mutate.battery import battery
from bohrin.mutate.equivalence import collides_under, provably_distinct


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("0", "[[0]]"),
        ("0", "[0]"),
        ("[0]", "[[0]]"),
        ("7", "[[7]]"),
        ("[[ 3 ]]", "3"),
        ("(5,)", "[5]"),
    ],
)
def test_one_cell_spellings_collide(left: str, right: str) -> None:
    assert collides_under(left, right) is not None
    assert not provably_distinct(left, right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("0", "[[1]]"),  # a different cell
        ("0", "[[0, 0]]"),  # more than one cell
        ("0", "[[0], [0]]"),  # more than one row
        ("0", "[]"),  # no cell at all
        ("0", "[[]]"),
    ],
)
def test_different_answers_stay_distinct(left: str, right: str) -> None:
    """The counterweight: unwrapping must never merge answers that differ."""
    assert provably_distinct(left, right)


class _Constants(MutationOperator):
    """A third-party operator that claims every constant is wrong, with no guard of its own."""

    id = "constants"
    rationale = "test double"

    def apply(self, task: Task) -> Iterator[Candidate]:
        for literal in ("0", "[]"):
            yield Candidate(
                literal, Provenance(self.id, "constant", f"{literal} is not the answer"), Ground.DIFFERENTIAL
            )


def test_the_battery_suppresses_a_constant_that_is_the_one_cell_answer() -> None:
    task = Task(id="0", prompt="Output the grid.", reference="[[0]]", reward_fns=("g",))
    result = battery(task, [_Constants()])

    assert [c.payload for c in result.candidates] == ["[]"], "only the colliding constant is removed"
    assert result.suppressed == 1


def test_the_battery_keeps_a_constant_that_cannot_equal_the_grid() -> None:
    task = Task(id="0", prompt="Output the grid.", reference="[[1, 2], [3, 4]]", reward_fns=("g",))

    assert "0" in {c.payload for c in battery(task, [_Constants()]).grounded}
