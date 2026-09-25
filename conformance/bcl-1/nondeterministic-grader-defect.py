"""BCL-1 fixture: nondeterministic-grader, with defect BGW-127.

Task: solve(items) returns the sum of the items greater than zero.
Interface: grade(submission) -> float, where submission is the program's source.
The defect: each call checks two cases drawn at random, with no fixed seed, so a program that is
right on some cases and wrong on others gets different rewards for the same submission.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

#: Every case the grader checks: the argument, and the result a correct program returns.
CASES = [([], 0), ([1, -2, 3], 4), ([0], 0), ([5, 5], 10), ([-1, -1], 0)]


def _load(submission: str) -> Callable[..., object]:
    namespace: dict[str, Any] = {}
    exec(compile(submission, "<submission>", "exec"), namespace)
    solve: Callable[..., object] = namespace["solve"]
    return solve


def grade(submission: str) -> float:
    """1.0 when two randomly drawn cases give the right value."""
    try:
        solve = _load(submission)
        drawn = random.sample(CASES, 2)  # the defect: a different sample on every call
        return 1.0 if all(solve(list(argument)) == expected for argument, expected in drawn) else 0.0
    except Exception:
        return 0.0
