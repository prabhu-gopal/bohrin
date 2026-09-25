"""BCL-1 fixture: reference-wrong, with defect BGW-124.

Task: solve(items) returns the sum of the items greater than zero. Example: solve([1, -2, 3]) == 4.
Interface: grade(submission) -> float, where submission is the program's source.
The defect: its expected values come from a reference that sums every item, negative ones
included. They contradict the task's own example (it expects 2 where the task says 4), so a
correct program fails and the reference's mistake passes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

#: Expected values computed from a wrong reference that sums every item.
CASES = [([], 0), ([1, -2, 3], 2), ([0], 0), ([5, 5], 10), ([-1, -1], -2)]


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
