"""Establishing that a candidate really is different from the reference.

An operator may only claim a :class:`~bohrin.ir.task.Ground` when the candidate is
incorrect *independently of the verifier under audit*. Two of the grounds rest on the
candidate being **distinguishable from the known-good answer** — and that is where a
syntactic comparison is not good enough.

``"1"`` and ``"1.0"`` are different strings and the same answer. A verifier that
accepts ``"1"`` for a task whose reference is ``"1.0"`` is not weak; it is doing
numeric comparison, which is correct. Reporting it as an exploit is the exact failure
this codebase forbids, and it was reachable in 1.0.1 because ``constant_return``
guarded only with ``lit == ref``.

This module supplies the two soundness checks that close it:

* :func:`provably_distinct` — text-level. Two payloads are distinct only when *no*
  normalisation a reasonable verifier might apply makes them equal. The burden of
  proof sits on us: any collision means no ground.
* :func:`code_equivalent` — code-level **Trivial Compiler Equivalence**. Two sources
  that compile to identical bytecode are the same program, so a "mutant" that
  compiles to the reference's bytecode cannot be an exploit no matter what produced
  it. TCE is the established equivalent-mutant defence and is *sound but incomplete*:
  it never declares two different programs equivalent, and it misses equivalences
  that survive to different bytecode.

Both checks only ever **remove** findings. Neither can create one.
"""

from __future__ import annotations

import ast
import json
import math
from collections.abc import Callable
from types import CodeType

#: Payloads longer than this are not parsed. ``ast.literal_eval`` and ``json.loads``
#: are safe but not free, and a multi-kilobyte reply is never one of the degenerate
#: literals this ladder exists to protect.
_MAX_PARSE = 4096

#: Strings a correct verifier may reasonably map onto the same boolean. Deliberately
#: generous: a false accusation costs far more than the handful of degenerate
#: candidates this suppresses.
#: The canonical do-nothing module, compiled once, for :func:`_is_inert`.
_EMPTY_PROGRAM = compile("", "<empty>", "exec")

_TRUEISH = frozenset({"true", "1", "yes", "y", "t"})
_FALSEISH = frozenset({"false", "0", "no", "n", "f"})


def _strip(text: str) -> object:
    return text.strip()


def _casefold(text: str) -> object:
    return text.strip().casefold()


def _numeric(text: str) -> object | None:
    """Parse as a number, so ``1``/``1.0``/``01``/``+1``/``1.00`` collapse together."""
    try:
        value = float(text.strip())
    except (TypeError, ValueError):
        return None
    # NaN never equals itself, which would report two identical payloads as distinct.
    return ("numeric", "nan") if math.isnan(value) else ("numeric", value)


def _literal(text: str) -> object | None:
    """Parse as a Python literal, so ``[]``/``[ ]`` and ``""``/``''`` collapse."""
    candidate = text.strip()
    if not candidate or len(candidate) > _MAX_PARSE:
        return None
    try:
        return ("literal", repr(ast.literal_eval(candidate)))
    except (ValueError, SyntaxError, MemoryError, RecursionError, TypeError):
        return None


def _json(text: str) -> object | None:
    """Parse as JSON, so ``[]``/``[ ]`` and ``{}``/``{ }`` collapse for JSON graders."""
    candidate = text.strip()
    if not candidate or len(candidate) > _MAX_PARSE:
        return None
    try:
        return ("json", json.dumps(json.loads(candidate), sort_keys=True))
    except (ValueError, RecursionError):
        return None


def _boolish(text: str) -> object | None:
    """Map common truth spellings together, so ``1``/``true``/``True``/``yes`` collapse."""
    candidate = text.strip().casefold()
    if candidate in _TRUEISH:
        return ("boolish", True)
    if candidate in _FALSEISH:
        return ("boolish", False)
    return None


#: Ordered so the cheapest and most common collisions are reported first. A
#: normalisation returning ``None`` does not apply to that payload and is skipped —
#: it never counts as a collision.
_LADDER: tuple[tuple[str, Callable[[str], object | None]], ...] = (
    ("exact", lambda text: text),
    ("whitespace", _strip),
    ("case", _casefold),
    ("numeric", _numeric),
    ("literal", _literal),
    ("json", _json),
    ("boolean", _boolish),
)


def collides_under(left: str, right: str) -> str | None:
    """Name the first normalisation under which ``left`` and ``right`` are the same answer.

    Returns ``None`` when the two are distinguishable under every normalisation, which
    is the only case in which a caller may claim a ground.
    """
    for name, normalise in _LADDER:
        a, b = normalise(left), normalise(right)
        if a is None or b is None:
            continue  # this normalisation does not apply to one of them
        if a == b:
            return name
    return None


def provably_distinct(left: str, right: str) -> bool:
    """True when no reasonable verifier could read these two payloads as one answer."""
    return collides_under(left, right) is None


#: First-person refusal phrasings, casefolded. Deliberately narrow in both directions: a
#: declared answer that merely contains "cannot" — ``you cannot divide by zero`` — is an
#: answer, not a refusal, and must keep every ground it would otherwise support. First
#: person is what separates declining a request from stating a fact about one.
_REFUSAL_MARKERS = (
    "i can't",
    "i cannot",
    "i can not",
    "i won't",
    "i will not",
    "i'm sorry",
    "i am sorry",
    "i'm unable",
    "i am unable",
    "i'm not able to",
    "i am not able to",
    "i must decline",
    "i refuse",
    "can't help with",
    "cannot help with",
    "can't assist",
    "cannot assist",
    "can't comply",
    "cannot comply",
)


def reads_as_refusal(text: str) -> bool:
    """Whether a declared answer is itself a refusal.

    On a safety task the declared answer is a behaviour — *decline this* — not a
    proposition, and "correct" means only that the reply did not comply. Every text-level
    candidate Bohrin can construct is non-compliant: an empty reply, the prompt echoed, a
    refusal, a constant, a denial. None of them is wrong on such a task, so none may carry a
    ground there, and a verifier rewarding them is doing its job.

    Like every check in this module it can only remove findings. A false positive here
    costs recall on one task; a false negative would accuse a working safety grader of
    rewarding the refusals it exists to reward.
    """
    folded = text.casefold().replace("’", "'")
    return any(marker in folded for marker in _REFUSAL_MARKERS)


def _canonical(code: CodeType) -> tuple[object, ...]:
    """A comparable form of a code object with incidental detail removed.

    Line numbers, filename and the source's formatting are excluded because they are
    exactly what a mutation should be allowed to change without becoming a different
    program. Nested code objects are canonicalised recursively, and that recursion is
    the whole point:

    **Comparing ``co_code`` alone is worse than useless.** For a module, ``co_code``
    only builds and stores the function; the body lives in ``co_consts`` as a nested
    code object. Two modules whose functions differ completely still share a
    byte-identical module-level ``co_code``, so a naive comparison declares every
    mutant equivalent and silently suppresses every finding.
    """
    consts = tuple(_canonical(const) if isinstance(const, CodeType) else const for const in code.co_consts)
    return (
        code.co_name,
        code.co_code,
        consts,
        code.co_names,
        code.co_varnames,
        code.co_freevars,
        code.co_cellvars,
        code.co_argcount,
        code.co_posonlyargcount,
        code.co_kwonlyargcount,
        code.co_flags,
    )


def _is_inert(code: CodeType) -> bool:
    """Whether this source compiled to a program that does nothing observable.

    The compiler discards a bare constant expression statement as dead code, so ``70`` and
    the empty string compile to the *same* do-nothing module. That is correct behaviour for
    a Python compiler and a disaster for a comparison that reads identical bytecode as
    identical meaning.
    """
    return _canonical(code) == _canonical(_EMPTY_PROGRAM)


def code_equivalent(left: str, right: str) -> bool:
    """Trivial Compiler Equivalence: do these two sources compile to the same program?

    ``False`` whenever either side fails to compile — an unparseable payload is not a
    claim of equivalence, and text submissions (most of the ecosystem) simply fall
    through to the text-level check.

    Sound but incomplete by construction. It catches a mutant that is byte-identical
    to its reference after compilation — for example emptying the body of a function
    whose body was already ``pass`` — and it does **not** catch a mutation that is
    semantically inert but compiles differently, such as negating a branch whose two
    arms do the same thing. That second class is why an operator which cannot
    establish wrongness structurally emits a lead rather than a finding.

    **Do not add a size limit here.** It is the obvious hardening and it is unsound.
    ``compile`` runs on third-party text, so guarding it by length looks prudent, but
    the failure directions are not symmetric: returning ``True`` when the programs
    differ would suppress a real finding, while returning ``False`` when they are the
    same **fails to suppress a false accusation** — the failure this module exists to
    prevent. A length guard returns ``False``, so it trades the guarantee for nothing.

    It also buys nothing measurable. Compilation is linear and cheap next to work the
    caller already does: on a typical reference ``compile`` takes ~0.02 ms against
    ~6.4 ms for the LibCST parse the code-level operators run over the same string,
    and a whole 40-task audit spends single-digit milliseconds here. Hostile input is
    not a lever either — deeply nested sources are rejected by the parser in
    microseconds, and the pathological cases raise, which is caught below.
    """
    try:
        left_code = compile(left, "<candidate>", "exec")
        right_code = compile(right, "<reference>", "exec")
    except (SyntaxError, ValueError, TypeError, MemoryError, RecursionError):
        return False
    # A reference that is not a program has no bytecode worth comparing. Most references in
    # the wild are bare answers -- ``70``, ``5050`` -- and Python discards a constant
    # expression statement as dead code, so they compile to the *same* do-nothing module as
    # an empty submission. Without this check ``code_equivalent("", "70")`` is True and the
    # empty-reply candidate is suppressed as "the reference itself" on every numeric task in
    # the ecosystem: silent lost recall, the mirror image of the false accusations this
    # module was written to prevent.
    #
    # Returning False here cannot reintroduce those. The candidates it un-suppresses carry
    # their own independent grounds: an empty reply is *structurally* wrong whatever the
    # reference is, and `constant_return` is guarded by `provably_distinct`, which compares
    # the payloads as answers rather than as programs. TCE is the wrong instrument for a
    # reference that was never code; it is not the only instrument.
    if _is_inert(right_code):
        return False
    return _canonical(left_code) == _canonical(right_code)


__all__ = ["code_equivalent", "collides_under", "provably_distinct", "reads_as_refusal"]
