"""BCL-1 fixture: lenient-checker, with defect BGW-123. An input/output task.

Task: read integers separated by spaces and print them in ascending order, separated by spaces.
Interface: grade(output) -> float, where output is what the program printed for INPUT.
The defect: it checks only that every expected token appears somewhere in the output, ignoring
their order and any extra tokens, so unsorted or padded output passes.
"""

from __future__ import annotations

INPUT = "3 1 2\n"
EXPECTED = "1 2 3"


def grade(output: str) -> float:
    """1.0 when every expected token appears in the output."""
    return 1.0 if set(EXPECTED.split()) <= set(output.split()) else 0.0
