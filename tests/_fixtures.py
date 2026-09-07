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
import json
from collections.abc import Callable
from typing import Any

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


#: Graders that are **correct but not exact-string**, as ``(name, reference, equal)``.
#:
#: This table is the guard that 1.0.1 was missing. ``strict_source`` above accepts only a
#: byte-identical reference, so it models a strict verifier and can never catch an operator
#: that mistakes a *rendering* difference for a *behaviour* difference. Every grader here
#: is right to accept what it accepts, so a probe reporting any finding against one of them
#: is falsely accusing a correct verifier.
#:
#: The references are chosen to collide with ``constant_return``'s literals under exactly
#: one normalisation each, which is how the defect was originally reproduced.
LENIENT_CORRECT: tuple[tuple[str, str, Callable[[str, str], bool]], ...] = (
    ("numeric", "1.0", lambda reply, ref: _as_float(reply) is not None and _as_float(reply) == _as_float(ref)),
    ("numeric-zero", "0.0", lambda reply, ref: _as_float(reply) is not None and _as_float(reply) == _as_float(ref)),
    ("trailing-zeros", "1.00", lambda reply, ref: _as_float(reply) is not None and _as_float(reply) == _as_float(ref)),
    ("case-folding", "true", lambda reply, ref: reply.strip().casefold() == ref.strip().casefold()),
    ("case-folding-none", "none", lambda reply, ref: reply.strip().casefold() == ref.strip().casefold()),
    ("json-equal", "[ ]", lambda reply, ref: _as_json(reply) is not None and _as_json(reply) == _as_json(ref)),
    ("whitespace", "  42  ", lambda reply, ref: reply.strip() == ref.strip()),
)


def _as_float(text: str) -> float | None:
    try:
        return float(text.strip())
    except (TypeError, ValueError):
        return None


def _as_json(text: str) -> str | None:
    try:
        return json.dumps(json.loads(text.strip()), sort_keys=True)
    except (ValueError, RecursionError):
        return None


def lenient_source(reference: str, equal: Callable[[str, str], bool], n: int = 2) -> MemorySource:
    """A verifier that is lenient about presentation and still entirely correct."""
    return MemorySource(
        _tasks(n, reference=reference),
        lambda task, payload: 1.0 if equal(payload, task.reference or "") else 0.0,
    )


#: A reference whose function bodies are already ``pass``. Emptying them produces a mutant
#: byte-identical to the reference the verifier has just accepted as correct, so reporting
#: it is an accusation that the verifier accepted its own known-good answer.
TRIVIAL_REFERENCE = "def solve(items):\n    pass\n"

#: A reference where negating the branch predicate cannot change behaviour, because both
#: arms do the same thing. The textbook equivalent mutant.
EQUIVALENT_BRANCH_REFERENCE = "def solve(x):\n    if x > 0:\n        return abs(x)\n    return abs(x)\n"


def exact_match_source(reference: str, n: int = 2) -> MemorySource:
    """A correct exact-match verifier over a caller-supplied reference."""
    return MemorySource(
        _tasks(n, reference=reference),
        lambda task, payload: 1.0 if payload == task.reference else 0.0,
    )


def substring_source(reference: str = REFERENCE, n: int = 2) -> MemorySource:
    """A genuinely weak verifier: anything containing the answer passes.

    Not a clean fixture — this one *should* produce findings. It is here so the
    false-accusation tests can prove they have not simply disabled the probe.
    """
    return MemorySource(
        _tasks(n, reference=reference), lambda task, payload: 1.0 if (task.reference or "") in payload else 0.0
    )


def behavioural_source(reference: str, inputs: tuple[int, ...], n: int = 2) -> MemorySource:
    """A correct verifier that **executes** the submission and compares its outputs.

    This is the only shape of fixture that can catch an equivalent mutant being reported.
    A textual grader rejects a mutated source outright — it is not the reference string —
    so the mutation never reaches the verdict and the test passes for the wrong reason.
    A behavioural grader accepts any program that behaves like the reference, which is
    precisely correct, and therefore accepts an inert mutation. If the operator that
    produced it claimed a ground, that acceptance becomes a false accusation.

    Executes fixture-local code only, on inputs this module supplies.
    """

    def outputs(source: str) -> list[object] | None:
        namespace: dict[str, Any] = {}
        try:
            exec(compile(source, "<fixture>", "exec"), namespace)
            solve = namespace["solve"]
            return [solve(value) for value in inputs]
        except Exception:
            return None

    expected = outputs(reference)

    def grade(_task: Task, payload: str) -> float:
        produced = outputs(payload)
        return 1.0 if produced is not None and produced == expected else 0.0

    return MemorySource(_tasks(n, reference=reference), grade)


def exploding_source(n: int = 2) -> MemorySource:
    """A verifier that raises. Used to prove one bad task cannot abandon an audit."""

    def grade(task: Task, payload: str) -> float:
        raise RuntimeError(f"verifier blew up on {task.id}")

    return MemorySource(_tasks(n), grade)


__all__ = [
    "EQUIVALENT_BRANCH_REFERENCE",
    "LENIENT_CORRECT",
    "REFERENCE",
    "TRIVIAL_REFERENCE",
    "behavioural_source",
    "broken_baseline_source",
    "exact_match_source",
    "exploding_source",
    "flaky_source",
    "lenient_source",
    "no_reference_source",
    "strict_source",
    "substring_source",
    "weak_source",
]
