"""Synthetic graders with known behaviour, correct and weak.

Every definition is tested from both directions:

* against **correct** graders, where no grounded candidate may ever be accepted — one that is
  would be a false accusation, and fails the build;
* against **weak** graders, where grounded candidates must still be accepted — otherwise a
  guard has simply switched the battery off.

The first matters more. Bohrin's governing rule is that it must never falsely accuse a
verifier, so the correct graders are the guard that keeps the definitions honest.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from bohrin.ir.task import Task

#: A grader: given the task and the submitted payload, does it pay full marks?
Grader = Callable[[Task, str], bool]

REFERENCE = """def solve(items):
    total = 0
    for item in items:
        if item > 0:
            total += item
    return total
"""


def task(reference: str | None = "70", prompt: str = "What is the value?", task_id: str = "t0") -> Task:
    return Task(id=task_id, prompt=prompt, reference=reference, reward_fns=("r",))


#: Graders that are **correct but not exact-string**, as ``(name, reference, equal)``.
#:
#: An exact-string matcher models a strict verifier and can never catch an operator that
#: mistakes a *rendering* difference for a *behaviour* difference. Every grader here is right
#: to accept what it accepts, so a grounded candidate it accepts is a false accusation.
#:
#: The references are chosen to collide with ``constant_return``'s literals under exactly one
#: normalisation each, which is how the defect was originally reproduced.
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


#: A reference whose function bodies are already ``pass``. Emptying them produces a mutant
#: byte-identical to the reference, so calling it wrong accuses a verifier of accepting its
#: own known-good answer.
TRIVIAL_REFERENCE = "def solve(items):\n    pass\n"

#: A reference where negating the branch predicate cannot change behaviour, because both
#: arms do the same thing. The textbook equivalent mutant.
EQUIVALENT_BRANCH_REFERENCE = "def solve(x):\n    if x > 0:\n        return abs(x)\n    return abs(x)\n"


def behavioural_grader(reference: str, inputs: tuple[int, ...]) -> Callable[[str], bool]:
    """A correct grader that **executes** the submission and compares its outputs.

    The only shape of grader that can catch an equivalent mutant being called wrong: a
    textual grader rejects a mutated source outright, while a behavioural one accepts any
    program that behaves like the reference — which is precisely correct.

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
    return lambda payload: (produced := outputs(payload)) is not None and produced == expected


__all__ = [
    "EQUIVALENT_BRANCH_REFERENCE",
    "LENIENT_CORRECT",
    "REFERENCE",
    "TRIVIAL_REFERENCE",
    "Grader",
    "behavioural_grader",
    "task",
]
