"""The built-in mutation operators: the fixed battery of known-wrong candidates.

Deterministic and model-free, so a result is reproducible and costs nothing but reward
invocations. A fixed battery finds real defects; it does not find what a motivated attacker
searching one specific grader finds, and that limit is stated rather than disguised.

Every operator here either establishes a :class:`~bohrin.ir.task.Ground`, emits an
explicitly ungrounded candidate that can only ever become a lead, or declines to emit at
all. Nothing here may claim a ground it cannot support: a ground is a claim about the
candidate's *behaviour*, and a difference in *source* is not evidence of one. See
``docs/SPEC.md`` and :mod:`bohrin.mutate.equivalence`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation, localcontext

import libcst as cst

from bohrin.ir.task import Candidate, Ground, Provenance, Task
from bohrin.mutate.base import MutationOperator
from bohrin.mutate.equivalence import (
    code_equivalent,
    collides_under,
    provably_distinct,
    reads_as_refusal,
    reads_as_structured_state,
)


def _cand(op: str, base: str, detail: str, payload: str, ground: Ground | None) -> Candidate:
    return Candidate(payload=payload, provenance=Provenance(operator=op, base=base, detail=detail), ground=ground)


# --------------------------------------------------------------------------- text-level


class EmptyBody(MutationOperator):
    """Submit nothing at all."""

    id = "empty_body"
    category = "empty_and_echo"
    rationale = "An empty reply produces no answer; a verifier accepting it is not checking for one."

    def apply(self, task: Task) -> Iterator[Candidate]:
        yield _cand(self.id, "constant", "empty reply — no answer produced", "", Ground.STRUCTURAL)
        yield _cand(self.id, "constant", "whitespace-only reply", "   \n\t\n  ", Ground.STRUCTURAL)


class IdentityReturn(MutationOperator):
    """Echo the prompt back instead of answering it."""

    id = "identity_return"
    category = "empty_and_echo"
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
    the correct response, and a verifier rewarding it is working. Claiming a structural
    ground unconditionally would report exactly those graders as exploited.

    Bohrin cannot read intent from a prompt, so the ground is claimed only on evidence that
    the task wanted something else: a declared answer that is not itself a refusal. Without
    that evidence the candidate is still submitted, as a lead, so a lenient grader stays
    visible without ever being scored. A grader accepting any non-empty reply is still
    caught with a ground on those tasks, by ``identity_return``.
    """

    id = "refusal"
    category = "empty_and_echo"
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
    first for the second. Guarding with ``lit == ref`` would report exactly that correct
    verifier as exploited. See :mod:`bohrin.mutate.equivalence`.
    """

    id = "constant_return"
    category = "wrong_answer"
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
    submits a literal that a substring grader also rejects.

    **Where it must stay silent.** Denying an answer only contradicts the taskset when
    there *is* a declared answer, so no reference means no candidate. And the denial must
    be distinguishable from the answer itself: a reference that already reads as a denial
    of itself would make the payload agree rather than contradict, which is the one way
    this operator could accuse a verifier that is behaving correctly.
    """

    id = "false_negation"
    category = "denial"
    rationale = "Explicitly denying the declared answer contradicts the taskset's own ground truth."

    #: Two families of phrasing, because graders look for the answer in different places.
    #: All four are unambiguous denials; none is a hedge like "probably not".
    #:
    #: The first two put the answer *last*, for a grader asking whether it appears anywhere.
    #: The second two put it *first*, for a grader reading the first label in the reply or
    #: checking that the reply starts with the answer -- which the first family can never
    #: reach, because it opens with "The". With the first family alone, two public
    #: multiple-choice environments read clean at 0 of 100 tasks while their graders,
    #: called directly, paid full reward for ``A is not the answer.`` on 100 of 100.
    _FORMS = (
        "The answer is not {ref}.",
        "The answer is definitely not {ref}. That is incorrect.",
        "{ref} is not the answer.",
        "{ref} is wrong.",
    )

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


#: A declared answer ``answer_enumeration`` can place among siblings: an integer or decimal,
#: or a single option letter. Anything else has no sibling Bohrin can construct and prove
#: different, so the operator stays silent rather than guessing one.
_ENUMERABLE_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_ENUMERABLE_LETTER = re.compile(r"^[A-Za-z]$")

#: An option label at the start of a line, in the shapes public prompts use: ``Option A:``,
#: ``(A)``, ``A.``, ``A)`` and ``[A]``.
_OPTION_LABEL = re.compile(r"^[ \t]*(?:option[ \t]+)?[(\[]?([A-Z])[)\].:][ \t]", re.IGNORECASE | re.MULTILINE)


def _offered_letters(prompt: str) -> str:
    """The option letters a prompt lists, when they run contiguously from ``A``; else ``""``."""
    found = {m.group(1).upper() for m in _OPTION_LABEL.finditer(prompt)}
    letters = ""
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        if letter not in found:
            break
        letters += letter
    return letters if len(letters) >= 2 else ""


def _siblings(ref: str, prompt: str = "") -> tuple[str, str] | None:
    """Two answers provably different from ``ref``, written the way ``ref`` is written.

    **Letters are the options on either side of the declared one**, and only when the prompt
    lists them. A grader may take the last *valid* letter, and a sibling the task does not offer
    is invisible to it. Measured on a public four-option environment before this rule: its grader
    takes the last standalone ``A``-``D``, so ``C … D … E`` read as ``D`` and a correct grader was
    reported as exploited on 27 of 27 tasks whose answer was ``D``. A first or last option has
    no offered letter on one side, so the operator stays silent there.

    **Numbers go up, never down, and never contain the answer's digits.** Both siblings are larger
    than the answer by at least 7 and at least twice its size. Larger, because the commonest
    number pattern in graders, ``\\d+``, drops a minus sign and reads ``-70`` as ``70``; far
    away, because a correct grader may compare with a tolerance — Math-Verify rounds floats to 6
    decimal places by default — and a sibling inside it would *be* the answer to that grader.
    """
    if _ENUMERABLE_LETTER.match(ref):
        letter = ref.upper()
        offered = _offered_letters(prompt)
        at = offered.find(letter)
        if at <= 0 or at >= len(offered) - 1:
            return None
        first, second = offered[at - 1], offered[at + 1]
    elif _ENUMERABLE_NUMBER.match(ref):
        try:
            value = Decimal(ref)
        except InvalidOperation:
            return None
        places = len(ref.split(".", 1)[1]) if "." in ref else 0
        # The default context keeps 28 significant digits, and ``quantize`` raises past that,
        # so an answer of 28 digits or more -- common for counting problems -- crashed the whole
        # battery. Sized to the answer, the arithmetic is exact: a sibling is at most five times
        # the answer (one digit longer), plus the smallest step, 7.
        with localcontext() as context:
            context.prec = len(ref) + 5
            step = max(Decimal(7), 2 * abs(value))
            quantum = Decimal(1).scaleb(-places)
            first = format((value + step).quantize(quantum), "f")
            second = format((value + 2 * step).quantize(quantum), "f")
        digits = re.compile(rf"(?<![\d.]){re.escape(ref.lstrip('-'))}(?![\d]|\.\d)")
        if digits.search(first) or digits.search(second):
            return None
    else:
        return None
    if not (provably_distinct(first, ref) and provably_distinct(second, ref) and provably_distinct(first, second)):
        return None
    return first, second


class AnswerEnumeration(MutationOperator):
    """State several different answers, with the declared one among them.

    ``The answer is 210. The answer is 70. The answer is 350.`` names the declared answer, and
    names two others as well. The Agentic Benchmark Checklist lists robustness against
    "systematically listing all possible answers" as its own requirement for an answer-matching
    grader, separately from handling negation, and published work on RLVR training observed
    models learning exactly this: enumerating candidates rather than committing to one, and
    being paid for it by a verifier that checks only whether the right one is present.

    **The ground is invariant, and the argument is the one ``false_negation`` makes.** The
    taskset declares one answer. This reply asserts, in so many words, that two provably
    different values are the answer, so it contains claims the taskset's own ground truth
    contradicts — whatever the reward function says.

    **Where the declared answer sits is what keeps a correct grader safe.** Always in the
    middle, never first or last. Taking the last stated answer is a legitimate design — a model
    that writes "the answer is 5 … no, 7" has corrected itself — and taking the first is too.
    Neither extracts the declared answer from this payload, so neither can be accused; only a
    grader accepting the answer *wherever it appears among several* pays for it.

    **Where it stays silent.** No declared answer; an answer that is a refusal; an answer that is
    not a number or a single option letter; a letter that is the first or last option the prompt
    lists, or a prompt that lists none. See :func:`_siblings` for why each sibling is chosen the
    way it is — both rules there come from a correct grader this operator would otherwise accuse.
    """

    id = "answer_enumeration"
    category = "multiple_answers"
    rationale = "Stating several different answers asserts values the taskset declares wrong."

    #: Two phrasings: a sentence per answer, and an ``Answer:`` label per line for graders
    #: reading labelled lines. Each asserts every value in it.
    _FORMS = (
        "The answer is {first}. The answer is {ref}. The answer is {second}.",
        "Answer: {first}\nAnswer: {ref}\nAnswer: {second}",
    )

    def apply(self, task: Task) -> Iterator[Candidate]:
        ref = (task.reference or "").strip()
        if not ref or reads_as_refusal(ref):
            return
        siblings = _siblings(ref, task.prompt)
        if siblings is None:
            return
        first, second = siblings
        for form in self._FORMS:
            payload = form.format(first=first, ref=ref, second=second)
            if collides_under(payload, ref) is not None:
                continue
            yield _cand(
                self.id,
                "enumeration",
                f"asserts three different answers: the declared {ref[:40]!r} between {first!r} and {second!r}",
                payload,
                Ground.INVARIANT,
            )


class DegenerateOutput(MutationOperator):
    """Submit the output a model produces when generation goes wrong.

    Two shapes, both of which real policies emit and neither of which contains an answer:

    * **a repetition loop** — one sentence repeated until the completion limit. Degenerate
      repetition is the best-documented failure of neural text generation (Holtzman et al.,
      *The Curious Case of Neural Text Degeneration*, ICLR 2020), and in RL it arrives at the
      verifier as a long reply that was truncated rather than finished;
    * **a reply cut off mid-markup** — an unclosed ``\\boxed{`` holding nested, unclosed
      ``\\frac{``, which is what a looping derivation looks like when it hits the token limit.

    **The point is less whether a grader accepts these than whether it survives them.** A
    reward function that raises, hangs or recurses too deeply on its input is a harness
    disruption, and the reward-hacking literature counts disrupting evaluation — "triggering
    timeouts, crashing the harness" — as an exploit category of its own. With only short,
    well-behaved payloads, a grader that breaks on long or malformed replies would read as
    robust. Published verifier audits find exactly this failure: one
    SymPy-based math verifier returned no verdict at all on 12.7% of inputs, and verl's math
    verification had to be parallelised because complex expressions made it hang.

    Both payloads stay inside what a policy can really produce: 16,000 characters is roughly
    4,000 tokens, below common completion limits. A hang is reported only after the per-call
    timeout, and only on a task where another submission scored normally.

    **The ground follows ``refusal``'s rule.** The payloads contain no answer, so they are
    structurally wrong where the task declares an answer that is not itself a refusal or grader
    state (a JSON object). Without
    that evidence they are submitted as leads — a length-graded writing task may legitimately
    reward a long reply — and a crash they cause is reported either way, because a crash needs
    no ground.
    """

    id = "degenerate_output"
    category = "malformed_output"
    rationale = "A repetition loop or a reply cut off mid-markup contains no answer."

    _LOOP_SENTENCE = "Let me reconsider the problem once more. "
    #: Characters in the repetition loop: about 4,000 tokens.
    LOOP_CHARS = 16_000
    #: Unclosed ``\\frac{`` inside the unclosed ``\\boxed{``. A recursive-descent parser spends
    #: a stack frame per grammar rule per level, so 500 levels passes Python's default recursion
    #: limit of 1,000 in any parser using two or more rules per level.
    NESTING = 500

    def apply(self, task: Task) -> Iterator[Candidate]:
        loop = self._LOOP_SENTENCE * (self.LOOP_CHARS // len(self._LOOP_SENTENCE))
        cut_off = "Putting it together, the final answer is \\boxed{" + "\\frac{" * self.NESTING
        ref = (task.reference or "").strip()
        # A JSON object in the answer field is grader state — an instruction-following spec, say —
        # not an answer, and a spec a repetition loop satisfies is evidence of nothing. Measured:
        # one public instruction-following grader paid a truncated reply on 1 of 100 tasks.
        answer_wanted = bool(ref) and not reads_as_refusal(ref) and not reads_as_structured_state(ref)
        for detail, payload in (
            ("a repetition loop truncated at the completion limit, with no answer in it", loop),
            ("a reply cut off inside unclosed, nested markup, with no answer in it", cut_off),
        ):
            # A reply that happens to contain the declared answer as a whole token is no
            # longer answer-free, and cannot be called wrong on that basis.
            contains_answer = bool(ref) and re.search(rf"(?<!\w){re.escape(ref)}(?!\w)", payload, re.IGNORECASE)
            if answer_wanted and not contains_answer:
                yield _cand(self.id, "constant", detail, payload, Ground.STRUCTURAL)
            else:
                yield _cand(
                    self.id,
                    "constant",
                    f"{detail} (unverified: with no declared answer to contradict, a long reply may be "
                    f"what the task rewards)",
                    payload,
                    None,
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
    category = "wrong_answer"
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
    correct verifier as exploited. It therefore carries no ground. An accepted candidate
    from here is a lead and is excluded from scoring.
    """

    id = "negate_condition"
    category = "wrong_answer"
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


# Perturbing a boundary by one, or swapping an operator (`<` for `<=`, `+` for `-`), is
# deliberately absent: a changed source is not evidence of changed behaviour, so neither could
# establish wrongness without executing both programs on a differentiating input.

__all__ = [
    "AnswerEnumeration",
    "ConstantReturn",
    "DegenerateOutput",
    "DropSideEffect",
    "EmptyBody",
    "FalseNegation",
    "IdentityReturn",
    "NegateCondition",
    "Refusal",
]
