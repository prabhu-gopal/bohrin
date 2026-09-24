"""The battery: every candidate tried against a task, and the ground each one may claim.

Operators propose candidates. This module decides which of them may be *called wrong*, and
applies the rules every operator is held to — first-party and third-party alike, since a
third-party operator reaches the same seam with no privileged path and no review:

* **Only operators for the task's shape run.** An operator declares the grader shapes it
  applies to; one written for program graders says nothing about a container.
* **Duplicates are dropped.** Two programs equal after stripping, or two workspaces with the
  same file changes and commands, are one submission to any verifier, and sending both
  spends a grader call for no information.
* **A grounded submission that is, or writes, the reference is suppressed.** Under any
  reading a correct verifier may apply — as an answer (every normalisation in the equivalence ladder) or as a
  program (Trivial Compiler Equivalence) — such a candidate is the known-good answer, and
  reporting its acceptance would accuse a verifier of accepting its own answer — ``1``
  against a reference of ``1.0`` is the canonical case.
* **Grounds are withdrawn where the declared answer cannot support them.** On a task whose
  declared answer is itself a refusal, "correct" means only "did not comply", and every
  candidate here is non-compliant, so none may be called wrong. On a task whose declared
  "answer" is a JSON object, the field is grader state — a constraint spec, a game state —
  so grounds resting on the answer (``DIFFERENTIAL``, ``INVARIANT``) are withdrawn, while
  grounds needing no answer (an empty reply, an echo) are kept.

A withdrawn candidate is still tried: a verifier accepting it is worth a human's attention,
as a lead. Every rule here can only remove a ground. None can create one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from bohrin.ir.task import Candidate, Ground, Payload, Source, Task
from bohrin.mutate import discover
from bohrin.mutate.base import MutationOperator
from bohrin.mutate.equivalence import code_equivalent, collides_under, reads_as_refusal, reads_as_structured_state


@dataclass(frozen=True, slots=True)
class Battery:
    """The candidates for one task, and what the rules removed or downgraded."""

    task: Task
    candidates: tuple[Candidate, ...]
    #: Grounded candidates dropped because they *are* the reference.
    suppressed: int = 0
    #: Candidates whose ground was withdrawn, and which are therefore leads only.
    withdrawn: int = 0

    @property
    def grounded(self) -> tuple[Candidate, ...]:
        """The candidates that may be reported as exploits if a verifier accepts them."""
        return tuple(c for c in self.candidates if c.known_wrong)

    @property
    def leads(self) -> tuple[Candidate, ...]:
        """The candidates that can only ever be leads."""
        return tuple(c for c in self.candidates if not c.known_wrong)


def is_the_reference(payload: str, reference: str) -> bool:
    """Whether ``payload`` is the known-good answer, as an answer or as a program."""
    return collides_under(payload, reference) is not None or code_equivalent(payload, reference)


def _carries_the_reference(payload: Payload, reference: str) -> bool:
    """Whether a submission is, or writes, the known-good answer.

    A workspace that writes the reference into any file is suppressed too. That can only
    remove a ground: a workspace whose ground is real never needs a file that *is* the
    known-good solution.
    """
    if isinstance(payload, Source):
        return is_the_reference(payload.text, reference)
    return any(content is not None and is_the_reference(content, reference) for content in payload.files.values())


def battery(task: Task, operators: Sequence[MutationOperator] | None = None) -> Battery:
    """Every candidate the operators propose for ``task``, with the rules above applied.

    ``operators`` defaults to every registered operator, in id order. Either way, only those
    whose shapes include ``task.shape`` run.
    """
    ops = [
        op for op in (operators if operators is not None else discover()) if not op.shapes or task.shape in op.shapes
    ]
    reference = task.reference or ""
    refusal_task = bool(reference) and reads_as_refusal(reference)
    state_task = bool(reference) and reads_as_structured_state(reference)

    seen: set[str] = set()
    out: list[Candidate] = []
    suppressed = 0
    withdrawn = 0
    for op in ops:
        for cand in op.apply(task):
            key = cand.payload.key
            if key in seen:
                continue
            if cand.known_wrong and reference and _carries_the_reference(cand.payload, reference):
                suppressed += 1
                continue
            if cand.known_wrong and (
                refusal_task or (state_task and cand.ground in (Ground.DIFFERENTIAL, Ground.INVARIANT))
            ):
                cand = replace(cand, ground=None)
                withdrawn += 1
            seen.add(key)
            out.append(cand)
    return Battery(task=task, candidates=tuple(out), suppressed=suppressed, withdrawn=withdrawn)


__all__ = ["Battery", "battery", "is_the_reference"]
