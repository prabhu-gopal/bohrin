"""Which tasks an audit looks at when it cannot look at all of them.

``--max-tasks N`` takes the **first** N tasks, and a prefix is not a sample. Measured on a
published environment: a bound of 10 scored 0 and a bound of 20 scored 50 on the same
verifier, because the tasks carrying the defect sat at positions 11 and 12. That makes a
bounded rate a statement about the first N tasks and nothing else — while a published index
row reads as a statement about the environment.

Two further reasons a prefix is the wrong instrument here, both visible in the public
corpus: tasksets are frequently grouped by subject, difficulty or source, so the first N
tasks are not even a haphazard slice of the whole; and a rate from a non-random subset has
no valid interval around it, so the Wilson interval printed beside it would be describing a
population it was not drawn from.

A seeded uniform sample fixes both. The seed is required rather than implicit, and it is
recorded in the report, because a sample nobody can redraw is not reproducible — and the
whole claim of an index is that anyone with ``pip install`` can re-run it.
"""

from __future__ import annotations

import random

#: Every task was audited: either no bound, or a bound at least as large as the taskset.
ALL = "all"
#: The first N tasks, in the order the taskset yields them.
PREFIX = "prefix"
#: A uniform random sample of N of the taskset's tasks, drawn with a recorded seed.
RANDOM = "random"


def select_indices(total: int | None, bound: int | None, seed: int | None) -> tuple[list[int] | None, str]:
    """The task indices to audit, and the selection mode to report.

    ``None`` indices mean "take them in the order the taskset yields them", which covers
    both an unbounded audit and a prefix; a list means those positions specifically.

    ``total`` is the taskset's length, or ``None`` where it will not say. Sampling needs a
    length — you cannot draw uniformly from a population of unknown size — so a caller that
    wants ``RANDOM`` must establish the length first and refuse the run without it, rather
    than quietly degrading to a prefix under a flag that says otherwise.
    """
    if bound is None:
        return None, ALL
    if total is not None and bound >= total:
        return None, ALL
    if seed is None:
        return None, PREFIX
    if total is None:
        raise ValueError("a random sample needs the taskset's length, and this taskset does not report one")
    # Sorted so the audit still walks the taskset forward: random *selection* is the point,
    # random *order* is not, and an ordered walk keeps any caching the taskset does useful.
    return sorted(random.Random(seed).sample(range(total), bound)), RANDOM


__all__ = ["ALL", "PREFIX", "RANDOM", "select_indices"]
