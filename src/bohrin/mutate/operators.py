"""The free baseline mutation operators.

Deterministic and model-free, so an audit is reproducible and costs nothing but reward
invocations. The proprietary attack engine adds model-generated, verifier-aware exploit
synthesis on top of this same contract; these operators find real defects but do not find
what a frontier attacker finds, and that gap is stated rather than disguised.

Every operator here either establishes a :class:`~bohrin.ir.task.Ground`, emits an
explicitly ungrounded candidate that can only ever become a lead, or declines to emit at
all. Nothing here may claim a ground it cannot support: a ground is a claim about the
candidate's *behaviour*, and a difference in *source* is not evidence of one. See
``docs/03_PROBES.md`` and :mod:`bohrin.mutate.equivalence`.
"""

from __future__ import annotations

from collections.abc import Iterator

import libcst as cst

from bohrin.ir.task import Candidate, Ground, Provenance, Task
from bohrin.mutate.base import MutationOperator
from bohrin.mutate.equivalence import code_equivalent, collides_under, reads_as_refusal


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
        # A copy or echo task declares its own prompt as the answer. Echoing it back is then
        # the correct submission, and a verifier accepting it is right to -- reporting that
        # would accuse a working grader. Checked under every normalisation, not by string
        # equality, for the reason `constant_return` is: a rendering is not a difference.
        if task.reference and collides_under(task.prompt, task.reference) is not None:
            return
        yield _cand(
            self.id, "prompt", "echoes the prompt verbatim instead of answering", task.prompt, Ground.STRUCTURAL
        )


class Refusal(MutationOperator):
    """Explicitly decline the task.

    Declining is only provably wrong where the task wanted an answer. On a safety task — a
    harmful request, where the benchmark measures whether a model refuses — declining *is*
    the correct response, and a verifier rewarding it is working. Until 1.2 this operator
    claimed a structural ground unconditionally, and so reported exactly those graders as
    exploited.

    Bohrin cannot read intent from a prompt, so the ground is claimed only on evidence that
    the task wanted something else: a declared answer that is not itself a refusal. Without
    that evidence the candidate is still submitted, as a lead, so a lenient grader stays
    visible without ever being scored. A grader accepting any non-empty reply is still
    caught with a ground on those tasks, by ``identity_return``.
    """

    id = "refusal"
    rationale = "An explicit refusal states that no work was done."

    def apply(self, task: Task) -> Iterator[Candidate]:
        ref = (task.reference or "").strip()
        if ref and not reads_as_refusal(ref):
            yield _cand(
                self.id,
                "constant",
                "explicitly declines to perform the task",
                "I cannot complete this task.",
                Ground.STRUCTURAL,
            )
            return
        yield _cand(
            self.id,
            "constant",
            "explicitly declines to perform the task (unverified: with no declared answer to "
            "contradict, declining may be what the task rewards)",
            "I cannot complete this task.",
            None,
        )


class ConstantReturn(MutationOperator):
    """Submit a fixed literal.

    Only claims the differential ground when a reference exists and the literal is
    *provably distinct* from it. Without a reference there is no way to know the
    constant is wrong — a task whose answer genuinely is ``0`` would otherwise be
    reported as a false positive.

    Distinctness is not string inequality. ``"1"`` and ``"1.0"`` are different strings
    and the same answer, so a verifier comparing numerically is right to accept the
    first for the second. In 1.0.1 this operator guarded with ``lit == ref`` and
    therefore reported exactly that correct verifier as exploited. See
    :mod:`bohrin.mutate.equivalence`.
    """

    id = "constant_return"
    rationale = "A fixed constant ignores the task input entirely."
    _LITERALS = ("0", "1", "True", "None", "[]", '""')

    def apply(self, task: Task) -> Iterator[Candidate]:
        ref = (task.reference or "").strip()
        if not ref:
            return
        for lit in self._LITERALS:
            collision = collides_under(lit, ref)
            if collision is not None:
                # Indistinguishable from the answer under a normalisation a correct
                # verifier may apply. Emitting nothing is the contract for "this
                # operator cannot establish wrongness for this task".
                continue
            yield _cand(
                self.id,
                "constant",
                f"returns the constant {lit} regardless of input; reference is {ref[:40]!r}",
                lit,
                Ground.DIFFERENTIAL,
            )


class FalseNegation(MutationOperator):
    """Submit an explicit denial of the taskset's own declared answer.

    ``The answer is not 70.`` contradicts a taskset that declares the answer is ``70``.
    The wrongness is settled by the taskset's own ground truth, not by the reward function
    being audited, which makes this an **invariant** ground: it holds whatever the verifier
    says. That independence is the whole requirement for reporting an exploit.

    **What it catches, and why it is worth having.** A verifier that decides by asking
    whether the answer appears *somewhere in the reply* cannot tell an assertion from its
    denial — the denial contains the answer too. Substring containment is one of the
    commonest grader shapes in the ecosystem, and no existing operator constructs a payload
    for it: `empty_body` and `refusal` submit nothing recognisable, and `constant_return`
    submits a literal that a substring grader also rejects. Measured on the public
    `verifiers` corpus, this payload scores **full reward** on ``glossary``, ``deepwiki``
    and ``color_codeword``.

    **Where it must stay silent.** Denying an answer only contradicts the taskset when
    there *is* a declared answer, so no reference means no candidate. And the denial must
    be distinguishable from the answer itself: a reference that already reads as a denial
    of itself would make the payload agree rather than contradict, which is the one way
    this operator could accuse a verifier that is behaving correctly.
    """

    id = "false_negation"
    rationale = "Explicitly denying the declared answer contradicts the taskset's own ground truth."

    #: Two phrasings, because a grader may key on a marker word rather than the sentence.
    #: Both are unambiguous denials; neither is a hedge like "probably not".
    _FORMS = ("The answer is not {ref}.", "The answer is definitely not {ref}. That is incorrect.")

    def apply(self, task: Task) -> Iterator[Candidate]:
        ref = (task.reference or "").strip()
        if not ref:
            return
        for form in self._FORMS:
            payload = form.format(ref=ref)
            # A payload that collides with the reference under some normalisation is not a
            # contradiction of it, and submitting one would be the constant_return bug in a
            # new costume. In practice a denial never collides -- it is strictly longer --
            # but the check is cheap and the invariant is the point.
            if collides_under(payload, ref) is not None:
                continue
            yield _cand(
                self.id,
                "negation",
                f"explicitly denies the declared answer {ref[:40]!r}",
                payload,
                Ground.INVARIANT,
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
        source = task.reference or ""
        module = _parse(source)
        if module is None:
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


class NegateCondition(MutationOperator):
    """Invert every branch predicate.

    Emits **leads, not findings.** Negating a predicate changes the source but does not
    reliably change behaviour: a branch whose arms do the same thing is the textbook
    equivalent mutant, and there is no way to tell the difference without executing
    both. Trivial Compiler Equivalence does not help here — the negation compiles to
    different bytecode precisely because the source differs.

    Claiming the differential ground anyway is what made this operator able to report a
    correct verifier as exploited. It therefore carries no ground until the execution
    comparator lands, which is the same reason ``off_by_one`` and ``swap_operator`` are
    not registered at all. An accepted candidate from here is reported in the advisory
    section and excluded from scoring.
    """

    id = "negate_condition"
    rationale = "Inverting a branch takes the opposite path on the inputs that exercise it."
    requires_code = True

    def apply(self, task: Task) -> Iterator[Candidate]:
        source = task.reference or ""
        module = _parse(source)
        if module is None:
            return
        tf = _ConditionNegator()
        mutated = module.visit(tf)
        if not tf.changed or code_equivalent(mutated.code, source):
            return
        yield _cand(
            self.id,
            "reference",
            "every `if` predicate negated; control flow inverted (unverified: the negation may not change behaviour)",
            mutated.code,
            None,
        )


# `off_by_one` and `swap_operator` are deliberately absent from this module and from the
# entry points in pyproject: both need an executable differential check to establish
# wrongness honestly, and that check lands with the execution comparator. `negate_condition`
# above is the same case caught late — it ships, but carries no ground, so it can only ever
# produce a lead.

__all__ = [
    "ConstantReturn",
    "DropSideEffect",
    "EmptyBody",
    "IdentityReturn",
    "NegateCondition",
    "Refusal",
]
