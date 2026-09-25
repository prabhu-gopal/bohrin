"""BCL-1 fixture: nondeterministic-grader, correct.

Task: solve(items) returns the sum of the items greater than zero.
Interface: grade(submission) -> float, where submission is the program's source.
It checks the same cases in the same order every time, so one program always gets one reward.
"""

from __future__ import annotations

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
    """1.0 when the program returns exactly the right value, of exactly the right type, on every case."""
    try:
        solve = _load(submission)
        for argument, expected in CASES:
            result = solve(list(argument))
            if type(result) is not type(expected) or result != expected:
                return 0.0
    except BaseException:  # any failure, including an attempt to exit, is a failure
        return 0.0
    return 1.0
