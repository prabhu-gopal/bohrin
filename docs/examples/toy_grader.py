"""The grader under test in the reproduction example: the weak grader from the tutorial.

It checks that ``add`` exists and runs, never what it returns, so it pays for an emptied body.
In a real reproduction this module is the grader's owner's own code, already on their machine.
"""

from __future__ import annotations


def grade(submission: str) -> float:
    """Return 1.0 if the submission defines an ``add`` that runs, else 0.0."""
    namespace: dict[str, object] = {}
    try:
        exec(submission, namespace)
        namespace["add"](2, 3)  # type: ignore[operator]
    except Exception:
        return 0.0
    return 1.0
