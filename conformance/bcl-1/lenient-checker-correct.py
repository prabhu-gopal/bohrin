"""BCL-1 fixture: lenient-checker, correct. An input/output task.

Task: read integers separated by spaces and print them in ascending order, separated by spaces.
Interface: grade(output) -> float, where output is what the program printed for INPUT.
This checker accepts exactly the right tokens in the right order; only surrounding whitespace is
ignored.
"""

from __future__ import annotations

INPUT = "3 1 2\n"
EXPECTED = "1 2 3"


def grade(output: str) -> float:
    """1.0 when the printed tokens are exactly the expected ones, in order."""
    return 1.0 if output.split() == EXPECTED.split() else 0.0
