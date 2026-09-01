"""Synthetic verifiers with known defects, and one with none.

Every probe is tested from both directions:

* a **weak** fixture where the exact exploits are known — a probe that misses them fails
  the build;
* a **clean** fixture where the correct answer is zero findings — a probe that reports
  anything fails the build.

The second matters more. Bohrin's governing rule is that it must never falsely accuse a
verifier, so the clean fixture is the guard that keeps the product honest.
"""

from __future__ import annotations

import itertools

from bohrin.adapters.memory import MemorySource
from bohrin.ir.task import Task

REFERENCE = """def solve(items):
    total = 0
    for item in items:
        if item > 0:
            total += item
    return total
"""


def _tasks(n: int = 3, *, reference: str | None = REFERENCE) -> list[Task]:
    return [
        Task(
            id=f"task-{i}",
            prompt=f"Sum the positive numbers in the list (case {i}).",
            reference=reference,
            reward_fns=("exact_match",),
        )
        for i in range(n)
    ]


def weak_source(n: int = 3) -> MemorySource:
    """A verifier that accepts anything non-empty — the classic weak oracle.

    It never inspects behaviour, only that *something* was submitted, so every structural
    mutation slips through.
    """
    return MemorySource(_tasks(n), lambda _task, payload: 1.0 if payload.strip() else 0.0)


def strict_source(n: int = 3) -> MemorySource:
    """A verifier that accepts only the exact reference. Nothing wrong should be found."""
    return MemorySource(_tasks(n), lambda task, payload: 1.0 if payload == task.reference else 0.0)


def flaky_source(n: int = 3, *, flaky_tasks: frozenset[str] | None = None) -> MemorySource:
    """A verifier that alternates its reward on selected tasks."""
    which = flaky_tasks if flaky_tasks is not None else frozenset({"task-1"})
    counters: dict[str, itertools.count[int]] = {}

    def grade(task: Task, payload: str) -> float:
        if task.id not in which:
            return 1.0
        counter = counters.setdefault(task.id, itertools.count())
        return float(next(counter) % 2)

    return MemorySource(_tasks(n), grade)


def broken_baseline_source(n: int = 3) -> MemorySource:
    """A verifier that rejects even its own reference solution.

    This is a misconfigured harness, not a weak verifier. Without a green baseline an
    accepted mutant is indistinguishable from Bohrin submitting in a form the verifier
    cannot read, so the probe must refuse to score rather than report exploits.
    """
    return MemorySource(_tasks(n), lambda _task, payload: 1.0 if payload == "only-this-exact-string" else 0.0)


def no_reference_source(n: int = 3) -> MemorySource:
    """A weak verifier on tasks that ship no reference solution."""
    return MemorySource(
        _tasks(n, reference=None),
        lambda _task, payload: 1.0 if payload.strip() else 0.0,
    )


def exploding_source(n: int = 2) -> MemorySource:
    """A verifier that raises. Used to prove one bad task cannot abandon an audit."""

    def grade(task: Task, payload: str) -> float:
        raise RuntimeError(f"verifier blew up on {task.id}")

    return MemorySource(_tasks(n), grade)


__all__ = [
    "REFERENCE",
    "broken_baseline_source",
    "exploding_source",
    "flaky_source",
    "no_reference_source",
    "strict_source",
    "weak_source",
]
