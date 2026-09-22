"""One-cell answers: ``0``, ``[0]`` and ``[[0]]`` are the same answer.

Found by reviewing a finding Bohrin had already made, during the 2026-09-13 sweep. A public
grid-answer environment declares the answer ``[[0]]`` on some tasks, and its parser reads
space-separated digit rows as a grid -- the format its own prompts use -- so the reply ``0``
parses to ``[[0]]`` and earns full marks. That verifier is behaving correctly.
``constant_return`` claimed ``0`` was provably distinct from ``[[0]]`` and reported it as
exploited.

The ladder may only ever remove findings, so the counterweights matter most: a different
one-cell answer, and a genuinely multi-cell one, must stay distinct.
"""

from __future__ import annotations

import pytest

from bohrin.ir.task import Task
from bohrin.mutate.equivalence import collides_under, provably_distinct
from bohrin.mutate.operators import ConstantReturn


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


def test_constant_return_no_longer_accuses_a_one_cell_grid() -> None:
    """Before this: ``0`` was submitted against ``[[0]]`` carrying a differential ground."""
    task = Task(id="0", prompt="Output the grid.", reference="[[0]]", reward_fns=("g",))

    payloads = {c.payload for c in ConstantReturn().apply(task)}

    assert "0" not in payloads
    assert "[]" in payloads, "only the colliding literal is withheld"


def test_constant_return_still_probes_a_grid_it_cannot_equal() -> None:
    task = Task(id="0", prompt="Output the grid.", reference="[[1, 2], [3, 4]]", reward_fns=("g",))

    payloads = {c.payload for c in ConstantReturn().apply(task)}

    assert "0" in payloads
