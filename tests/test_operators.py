"""The operators and the equivalence rules they are held to.

Each operator proposes candidates and claims a ground only where wrongness is established by
construction. The equivalence checks decide when two payloads are really different, and both
of them can only ever remove a ground.
"""

from __future__ import annotations

import json
import re

import pytest

from _fixtures import task
from bohrin.ir.task import Ground
from bohrin.mutate import discover
from bohrin.mutate.battery import battery
from bohrin.mutate.equivalence import (
    code_equivalent,
    collides_under,
    provably_distinct,
    reads_as_refusal,
    reads_as_structured_state,
)
from bohrin.mutate.operators import (
    AnswerEnumeration,
    ConstantReturn,
    DegenerateOutput,
    DropSideEffect,
    FalseNegation,
    _siblings,
)

# ------------------------------------------------------------------------- the registry


def test_operators_are_discoverable_and_explain_themselves() -> None:
    ops = discover()

    assert {op.id for op in ops} >= {
        "empty_body",
        "identity_return",
        "refusal",
        "constant_return",
        "false_negation",
        "answer_enumeration",
        "degenerate_output",
        "drop_side_effect",
        "negate_condition",
    }
    assert all(op.rationale for op in ops), "an operator must explain why its output is wrong"


# ---------------------------------------------------------------------- distinctness


@pytest.mark.parametrize(
    ("literal", "reference", "normalisation"),
    [
        ("1", "1.0", "numeric"),
        ("0", "0.0", "numeric"),
        ("1", "01", "numeric"),
        ("1", "+1", "numeric"),
        ("1", "1.00", "numeric"),
        ("True", "true", "case"),
        ("None", "none", "case"),
        ("1", "yes", "boolean"),
        ("True", "1", "boolean"),
        ("[]", "[ ]", "literal"),
        ('""', "''", "literal"),
    ],
)
def test_renderings_of_one_answer_are_not_distinct(literal: str, reference: str, normalisation: str) -> None:
    assert collides_under(literal, reference) == normalisation
    assert not provably_distinct(literal, reference)


@pytest.mark.parametrize(
    ("literal", "reference"),
    [("0", "42"), ("1", "42"), ("1", "1.5"), ("1", "100"), ("[]", "[1]"), ('""', "hello"), ("True", "banana")],
)
def test_genuinely_different_answers_keep_their_ground(literal: str, reference: str) -> None:
    assert provably_distinct(literal, reference)


# ------------------------------------------------------- trivial compiler equivalence


def test_trivial_compiler_equivalence_ignores_formatting_only_changes() -> None:
    reference = "def solve(x):\n    if x > 0:\n        return x\n    return 0\n"
    commented = "def solve(x):\n    # unchanged\n    if x > 0:\n        return x\n    return 0\n"

    assert code_equivalent(reference, commented)
    assert code_equivalent(reference, "\n\n" + reference)


def test_trivial_compiler_equivalence_does_not_suppress_real_mutations() -> None:
    reference = "def solve(x):\n    if x > 0:\n        return x\n    return 0\n"

    assert not code_equivalent(reference, "def solve(x):\n    pass\n")
    assert not code_equivalent(reference, "def solve(x):\n    if not x > 0:\n        return x\n    return 0\n")
    assert not code_equivalent(reference, "I cannot complete this task.")


def test_equivalence_descends_into_nested_code_objects() -> None:
    """A module's own ``co_code`` only stores its functions; comparing that alone would call
    every mutant equivalent and silently suppress every finding."""
    one = "def f(x):\n    return x + 1\n"
    two = "def f(x):\n    return x * 999\n"

    assert compile(one, "<a>", "exec").co_code == compile(two, "<b>", "exec").co_code
    assert not code_equivalent(one, two)


@pytest.mark.parametrize("reference", ["70", "5050", "0", "1", "3.14", "True", "None"])
def test_a_bare_answer_is_not_a_program_and_suppresses_nothing(reference: str) -> None:
    assert not code_equivalent("", reference)
    assert not code_equivalent("0", reference) or reference == "0"
    assert not code_equivalent("I cannot complete this task.", reference)


def test_the_equivalence_check_still_catches_a_real_equivalent_mutant() -> None:
    trivial = "def solve(x):\n    pass\n"

    assert code_equivalent(trivial, trivial)
    assert code_equivalent(trivial, "def solve(x):\n    # unchanged\n    pass\n")
    assert not code_equivalent("def solve(x):\n    return 1\n", trivial)


# ------------------------------------------------------- refusals and grader state


@pytest.mark.parametrize(
    ("text", "is_refusal"),
    [
        ("I'm sorry, but I can't help with that.", True),
        ("I cannot assist with this request.", True),
        ("I’m unable to provide that.", True),
        ("You cannot divide by zero.", False),
        ("It can't be negative, so the answer is 4.", False),
        ("70", False),
    ],
)
def test_a_refusal_is_recognised_and_a_mere_negation_is_not(text: str, is_refusal: bool) -> None:
    assert reads_as_refusal(text) is is_refusal


@pytest.mark.parametrize(
    ("text", "is_state"),
    [
        ('{"func_name": "verify_postscript", "postscript_marker": "Addendum:"}', True),
        ('  {"remaining_words": ["DIRT"], "answer": [{"group": "X"}]}  ', True),
        ("{}", True),
        ("[[0]]", False),
        ('["A", "B"]', False),
        ("70", False),
        ("{not json", False),
        ("\\boxed{42}", False),
        ("The answer is {x}", False),
    ],
)
def test_only_a_json_object_reads_as_state(text: str, is_state: bool) -> None:
    assert reads_as_structured_state(text) is is_state


def test_a_long_spec_is_still_state() -> None:
    """No size limit: ``False`` keeps the grounds, so a limit would fail in the unsafe direction."""
    spec = json.dumps({"func_name": "verify_keywords", "original_prompt": "Write an essay. " * 800})
    assert len(spec) > 10_000
    assert reads_as_structured_state(spec) is True


# ------------------------------------------------------------------ constant_return


def test_constant_return_never_proposes_a_literal_that_is_the_answer() -> None:
    payloads = [c.payload for c in ConstantReturn().apply(task("0"))]

    assert "0" not in payloads
    assert payloads, "other literals are still legitimate candidates"


def test_operators_needing_a_reference_decline_without_one() -> None:
    t = task(None, prompt="Do something.")

    assert list(ConstantReturn().apply(t)) == []
    assert list(DropSideEffect().apply(t)) == []


# ------------------------------------------------------------------- false_negation


def test_every_denial_contradicts_rather_than_restates_the_answer() -> None:
    candidates = list(FalseNegation().apply(task("A")))

    assert len(candidates) == len(FalseNegation._FORMS)
    assert any(c.payload.startswith("A ") for c in candidates), "no form puts the answer first"
    assert all(c.ground is Ground.INVARIANT for c in candidates)
    assert all(" not " in c.payload or "wrong" in c.payload for c in candidates)


# --------------------------------------------------------------- answer_enumeration

_OPTIONS = "Which is it?\n\n(A) red\n(B) green\n(C) blue\n(D) yellow"
_STATED = re.compile(r"(?:answer is|Answer:)\s*([^\s.]+(?:\.\d+)?)")


@pytest.mark.parametrize(
    ("reference", "prompt", "expected"),
    [
        ("70", "", ("210", "350")),
        ("0", "", ("7", "14")),
        ("0.50", "", ("7.50", "14.50")),
        ("-3", "", ("4", "11")),
        ("B", _OPTIONS, ("A", "C")),
        ("c", _OPTIONS, ("B", "D")),
        ("B", "Option A: x\nOption B: y\nOption C: z", ("A", "C")),
    ],
)
def test_siblings_are_written_like_the_answer_and_provably_different(
    reference: str, prompt: str, expected: tuple[str, str]
) -> None:
    assert _siblings(reference, prompt) == expected
    assert all(provably_distinct(s, reference) for s in expected)


@pytest.mark.parametrize(
    ("reference", "prompt"),
    [
        ("Paris", ""),
        ("x + 1", ""),
        ("[1, 2]", ""),
        ("", ""),
        ("I cannot help with that.", ""),
        ("D", _OPTIONS),
        ("A", _OPTIONS),
        ("B", "Pick the best answer."),
    ],
)
def test_it_stays_silent_where_no_sibling_can_be_proven_different(reference: str, prompt: str) -> None:
    assert list(AnswerEnumeration().apply(task(reference, prompt=prompt))) == []


@pytest.mark.parametrize(
    "reference",
    ["9" * 28, "1" * 40, "12345678901234567890.123456789", "0." + "1" * 30, "7" * 200],
)
def test_long_numeric_answers_get_exact_siblings(reference: str) -> None:
    """Past 28 significant digits, the default decimal precision, this raised and took the
    whole battery down with it. The siblings must also be exact, not rounded: checked here
    against integer arithmetic on the answer scaled to an integer."""
    siblings = _siblings(reference)
    assert siblings is not None
    places = len(reference.split(".", 1)[1]) if "." in reference else 0
    scaled = int(reference.replace(".", ""))
    step = max(7 * 10**places, 2 * abs(scaled))
    for sibling, multiple in zip(siblings, (1, 2), strict=True):
        assert int(sibling.replace(".", "")) == scaled + multiple * step
        assert (len(sibling.split(".", 1)[1]) if "." in sibling else 0) == places
    assert battery(task(reference)).candidates


def test_a_long_negative_answer_is_declined_not_crashed_on() -> None:
    """Its first sibling would be the answer without its minus sign, which a grader dropping
    signs reads as the answer, so the operator stays silent -- and the battery still runs."""
    reference = "-" + "9" * 30
    assert _siblings(reference) is None
    assert battery(task(reference)).candidates


def test_the_declared_answer_is_never_first_or_last() -> None:
    for candidate in AnswerEnumeration().apply(task("70")):
        assert _STATED.findall(candidate.payload) == ["210", "70", "350"]
        assert candidate.ground is Ground.INVARIANT


# ---------------------------------------------------------------- degenerate_output


def test_the_degenerate_payloads_stay_inside_what_a_policy_can_produce() -> None:
    payloads = [c.payload for c in DegenerateOutput().apply(task("42"))]

    assert len(payloads) == 2
    assert all(len(p) <= DegenerateOutput.LOOP_CHARS for p in payloads)
    assert all("42" not in p for p in payloads), "a payload containing the answer could not be called wrong"


def test_degenerate_payloads_are_grounded_only_where_an_answer_is_declared() -> None:
    assert all(c.ground is Ground.STRUCTURAL for c in DegenerateOutput().apply(task("42")))
    assert all(c.ground is None for c in DegenerateOutput().apply(task(None)))


# ------------------------------------------------------------------------- one cell


@pytest.mark.parametrize(
    ("left", "right"),
    [("0", "[[0]]"), ("0", "[0]"), ("[0]", "[[0]]"), ("7", "[[7]]"), ("[[ 3 ]]", "3"), ("(5,)", "[5]")],
)
def test_one_cell_spellings_collide(left: str, right: str) -> None:
    assert collides_under(left, right) is not None
    assert not provably_distinct(left, right)
