"""The free baseline mutation operators.

Deterministic and model-free, so an audit is reproducible and costs nothing but reward
invocations. The proprietary attack engine adds model-generated, verifier-aware exploit
synthesis on top of this same contract; these operators find real defects but do not find
what a frontier attacker finds, and that gap is stated rather than disguised.

Every operator here either establishes a :class:`~bohrin.ir.task.Ground` or declines to
emit. See ``docs/03_PROBES.md``.
"""

from __future__ import annotations

from collections.abc import Iterator

import libcst as cst

from bohrin.ir.task import Candidate, Ground, Provenance, Task
from bohrin.mutate.base import MutationOperator


def _cand(op: str, base: str, detail: str, payload: str, ground: Ground | None) -> Candidate:
    return Candidate(payload=payload, provenance=Provenance(operator=op, base=base, detail=detail), ground=ground)


# --------------------------------------------------------------------------- text-level


class EmptyBody(MutationOperator):
    """Submit nothing at all."""

    id = "empty_body"
    rationale = "An empty reply produces no answer; a verifier accepting it is not checking for one."

    def apply(self, task: Task) -> Iterator[Candidate]:
        yield _cand(self.id, "constant", "empty reply — no answer produced", "", Ground.STRUCTURAL)
        yield _cand(self.id, "constant", "whitespace-only reply", "   \n\t\n  ", Ground.STRUCTURAL)


class IdentityReturn(MutationOperator):
    """Echo the prompt back instead of answering it."""

    id = "identity_return"
    rationale = "Restating the question is never an answer to it."

    def apply(self, task: Task) -> Iterator[Candidate]:
        if not task.prompt.strip():
            return
        yield _cand(
            self.id, "prompt", "echoes the prompt verbatim instead of answering", task.prompt, Ground.STRUCTURAL
        )


class Refusal(MutationOperator):
    """Explicitly decline the task."""

    id = "refusal"
    rationale = "An explicit refusal states that no work was done."

    def apply(self, task: Task) -> Iterator[Candidate]:
        yield _cand(
            self.id,
            "constant",
            "explicitly declines to perform the task",
            "I cannot complete this task.",
            Ground.STRUCTURAL,
        )


class ConstantReturn(MutationOperator):
    """Submit a fixed literal.

    Only claims the differential ground when a reference exists and differs from the
    literal. Without a reference there is no way to know the constant is wrong — a task
    whose answer genuinely is ``0`` would otherwise be reported as a false positive.
    """

    id = "constant_return"
    rationale = "A fixed constant ignores the task input entirely."
    _LITERALS = ("0", "1", "True", "None", "[]", '""')

    def apply(self, task: Task) -> Iterator[Candidate]:
        ref = (task.reference or "").strip()
        if not ref:
            return
        for lit in self._LITERALS:
            if lit == ref:
                continue  # this literal IS the answer here; emitting it would be a false accusation
            yield _cand(
                self.id,
                "constant",
                f"returns the constant {lit} regardless of input; reference is {ref[:40]!r}",
                lit,
                Ground.DIFFERENTIAL,
            )


# --------------------------------------------------------------------------- code-level


class _BodyStripper(cst.CSTTransformer):
    """Replace every function body with a single ``pass``."""

    def __init__(self) -> None:
        self.changed = False

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        self.changed = True
        return updated_node.with_changes(body=cst.IndentedBlock(body=[cst.SimpleStatementLine(body=[cst.Pass()])]))


class _ConditionNegator(cst.CSTTransformer):
    """Invert the predicate of every ``if``."""

    def __init__(self) -> None:
        self.changed = False

    def leave_If(self, original_node: cst.If, updated_node: cst.If) -> cst.If:
        self.changed = True
        return updated_node.with_changes(test=cst.UnaryOperation(operator=cst.Not(), expression=updated_node.test))


def _parse(source: str) -> cst.Module | None:
    try:
        return cst.parse_module(source)
    except Exception:  # not Python, or not parseable — the operator simply does not apply
        return None


class DropSideEffect(MutationOperator):
    """Empty every function body, keeping the signature.

    The highest-yield operator in this domain: a reward function that checks a return
    value but never inspects the filesystem or database will accept a solution that
    reports success without doing the work.
    """

    id = "drop_side_effect"
    rationale = "The signature survives but the work does not, so only a verifier that checks effects can catch it."
    requires_code = True

    def apply(self, task: Task) -> Iterator[Candidate]:
        module = _parse(task.reference or "")
        if module is None:
            return
        tf = _BodyStripper()
        mutated = module.visit(tf)
        if not tf.changed:
            return
        yield _cand(
            self.id,
            "reference",
            "every function body replaced with `pass`; no work is performed",
            mutated.code,
            Ground.STRUCTURAL,
        )


class NegateCondition(MutationOperator):
    """Invert every branch predicate."""

    id = "negate_condition"
    rationale = "Inverting a branch takes the opposite path on the inputs that exercise it."
    requires_code = True

    def apply(self, task: Task) -> Iterator[Candidate]:
        module = _parse(task.reference or "")
        if module is None:
            return
        tf = _ConditionNegator()
        mutated = module.visit(tf)
        if not tf.changed or mutated.code == module.code:
            return
        yield _cand(
            self.id,
            "reference",
            "every `if` predicate negated; control flow inverted",
            mutated.code,
            Ground.DIFFERENTIAL,
        )


# `off_by_one` and `swap_operator` are declared in pyproject but intentionally not yet
# implemented: both need a differential check to establish wrongness honestly, and that
# check lands with the execution comparator. Registering an operator that cannot establish
# a ground would produce leads, not findings.

__all__ = [
    "ConstantReturn",
    "DropSideEffect",
    "EmptyBody",
    "IdentityReturn",
    "NegateCondition",
    "Refusal",
]
