"""The built-in mutation operators: the fixed battery of known-wrong candidates.

Deterministic and model-free, so a result is reproducible and costs nothing but reward
invocations. A fixed battery finds real defects; it does not find what a motivated attacker
searching one specific grader finds, and that limit is stated rather than disguised.

Every operator here targets a class in the weakness list (``docs/WEAKNESSES.md``) and either
establishes a :class:`~bohrin.ir.task.Ground`, emits an explicitly ungrounded candidate that
can only ever become a lead, or declines to emit at all. Nothing here may claim a ground it
cannot support: a ground is a claim about the candidate's *behaviour*, and a difference in
*source* is not evidence of one. See ``docs/SPEC.md`` and :mod:`bohrin.mutate.equivalence`.
"""

from __future__ import annotations

from collections.abc import Iterator

import libcst as cst

from bohrin.ir.task import Candidate, Ground, Provenance, Shape, Source, Task
from bohrin.mutate.base import MutationOperator
from bohrin.mutate.equivalence import code_equivalent


def _cand(op: str, base: str, detail: str, payload: str, ground: Ground | None) -> Candidate:
    return Candidate(
        payload=Source(payload), provenance=Provenance(operator=op, base=base, detail=detail), ground=ground
    )


class _BodyStripper(cst.CSTTransformer):
    """Replace every function body with a single ``pass``."""

    def __init__(self) -> None:
        self.changed = False

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        """Replace this function's body; its signature, decorators and name are kept."""
        self.changed = True
        return updated_node.with_changes(body=cst.IndentedBlock(body=[cst.SimpleStatementLine(body=[cst.Pass()])]))


def _inert(statement: cst.BaseSmallStatement) -> bool:
    """A statement that does nothing: ``pass``, ``...``, a bare string, or ``raise NotImplementedError``."""
    if isinstance(statement, cst.Pass):
        return True
    if isinstance(statement, cst.Expr):
        return isinstance(statement.value, cst.Ellipsis | cst.SimpleString | cst.ConcatenatedString)
    if isinstance(statement, cst.Raise) and statement.exc is not None:
        raised = statement.exc.func if isinstance(statement.exc, cst.Call) else statement.exc
        return isinstance(raised, cst.Name) and raised.value == "NotImplementedError"
    return False


class _WorkFinder(cst.CSTVisitor):
    """Records whether any function in a module has a body that does work."""

    def __init__(self) -> None:
        self.does_work = False

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        """Mark the module as doing work if this function's body holds anything but no-ops."""
        body = node.body
        lines = body.body if isinstance(body, cst.IndentedBlock) else [body]
        for line in lines:
            if not (
                isinstance(line, cst.SimpleStatementLine | cst.SimpleStatementSuite) and all(map(_inert, line.body))
            ):
                self.does_work = True


def _parse(source: str) -> cst.Module | None:
    try:
        return cst.parse_module(source)
    except Exception:  # not Python, or not parseable — the operator simply does not apply
        return None


class DropSideEffect(MutationOperator):
    """Empty every function body, keeping the signature (BGW-101, trivial implementation).

    A grader that checks only that the code imports and runs, or that checks a return value
    but never the filesystem or database, accepts a solution that does no work.

    **The ground needs a reference that does work.** "The emptied program does no work" proves
    it wrong only if the reference does some. An interface, an abstract base class or a protocol
    has functions whose bodies are only docstrings, ``pass``, ``...`` or ``raise
    NotImplementedError``; emptying them removes nothing, and a correct grader of that interface
    is right to accept the result. So the operator stays silent unless at least one function in
    the reference does something else.
    """

    id = "drop_side_effect"
    category = "hollow_program"
    rationale = "The signature survives but the work does not, so only a verifier that checks effects can catch it."
    requires_code = True
    shapes = (Shape.PROGRAM,)

    def apply(self, task: Task) -> Iterator[Candidate]:
        """The reference with every function body emptied, or nothing if that proves nothing."""
        source = task.reference or ""
        module = _parse(source)
        if module is None:
            return
        finder = _WorkFinder()
        module.visit(finder)
        if not finder.does_work:
            return
        tf = _BodyStripper()
        mutated = module.visit(tf)
        # `changed` only records that the transformer fired. A reference whose bodies
        # are already `pass` produces a mutant identical to the reference, which the
        # verifier has just accepted as the known-good answer — reporting that as an
        # exploit accuses a verifier of accepting the correct solution.
        if not tf.changed or code_equivalent(mutated.code, source):
            return
        yield _cand(
            self.id,
            "reference",
            "every function body replaced with `pass`; no work is performed",
            mutated.code,
            Ground.STRUCTURAL,
        )


# Negating a condition, perturbing a boundary by one, or swapping an operator (`<` for `<=`,
# `+` for `-`) is deliberately absent: a changed source is not evidence of changed behaviour,
# so none of them could establish wrongness without executing both programs on a
# differentiating input.

__all__ = ["DropSideEffect"]
