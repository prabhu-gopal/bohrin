"""The operators and the equivalence rules they are held to.

Each operator proposes candidates and claims a ground only where wrongness is established by
construction. The equivalence checks decide when two payloads are really different, and both
of them can only ever remove a ground.
"""

from __future__ import annotations

import json

import pytest

from _fixtures import REFERENCE, TRIVIAL_REFERENCE, task, text
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
from bohrin.mutate.operators import DropSideEffect

# ------------------------------------------------------------------------- the registry


def test_operators_are_discoverable_and_explain_themselves() -> None:
    ops = discover()

    assert [op.id for op in ops] == ["drop_side_effect"]
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


# ------------------------------------------------------------------ drop_side_effect


def test_emptying_every_body_is_structurally_wrong() -> None:
    (candidate,) = DropSideEffect().apply(task(REFERENCE))

    assert candidate.ground is Ground.STRUCTURAL
    assert "def solve(items):" in text(candidate), "the signature survives"
    assert "total" not in text(candidate), "the work does not"


@pytest.mark.parametrize("reference", [None, "", "70", "not python at all (", TRIVIAL_REFERENCE])
def test_it_stays_silent_where_emptying_proves_nothing(reference: str | None) -> None:
    """No reference, no function, unparseable source, or bodies that are already empty."""
    assert list(DropSideEffect().apply(task(reference))) == []


def test_the_battery_grounds_it_on_a_real_program() -> None:
    assert [c.provenance.operator for c in battery(task(REFERENCE)).grounded] == ["drop_side_effect"]


#: References whose functions do no work of their own: an interface, an abstract base, a protocol.
#: Emptying them removes nothing, so "the emptied program does no work" proves nothing about it.
_INERT_REFERENCES = {
    "docstring only": 'class Store:\n    def get(self, key):\n        """Return the value for key."""\n',
    "raises NotImplementedError": "class Store:\n    def get(self, key):\n        raise NotImplementedError\n",
    "raises NotImplementedError with a message": (
        'class Store:\n    def get(self, key):\n        """Return it."""\n'
        '        raise NotImplementedError("subclass")\n'
    ),
    "ellipsis": "class Store:\n    def get(self, key): ...\n",
    "only an empty nested function": "def outer():\n    def inner():\n        pass\n",
    "only an empty nested class": "def outer():\n    class Inner:\n        pass\n",
    "only evaluates its parameter": "def f(x):\n    x\n",
    "only a bare number": "def f():\n    0\n",
    "a bare return": "def f():\n    return\n",
    "returns None": "def f():\n    return None\n",
}


@pytest.mark.parametrize("reference", _INERT_REFERENCES.values(), ids=_INERT_REFERENCES.keys())
def test_emptying_a_reference_that_does_no_work_is_never_grounded(reference: str) -> None:
    """A correct grader of an interface accepts the emptied interface, and is right to."""
    assert [c for c in battery(task(reference)).grounded if c.provenance.operator == "drop_side_effect"] == []


def test_one_function_that_does_work_is_enough_for_the_ground() -> None:
    """The counterweight: an abstract method beside a real one still proves the emptied version wrong."""
    mixed = (
        "class Store:\n"
        "    def get(self, key):\n        raise NotImplementedError\n"
        "    def size(self):\n        return len(self.items)\n"
    )
    (candidate,) = DropSideEffect().apply(task(mixed))
    assert candidate.ground is Ground.STRUCTURAL


def test_a_nested_function_that_does_work_still_grounds_the_candidate() -> None:
    """The counterweight to skipping nested definitions: their bodies are still checked."""
    reference = "def outer(items):\n    def total():\n        return sum(items)\n    return total()\n"
    (candidate,) = DropSideEffect().apply(task(reference))
    assert candidate.ground is Ground.STRUCTURAL


@pytest.mark.parametrize("reference", ["def f():\n    return\n", "def f():\n    return None\n"])
def test_the_operator_itself_never_emits_an_emptying_that_changes_nothing(reference: str) -> None:
    """``return`` does work in form only: emptied to ``pass`` it compiles to the same program.

    The battery also suppresses equivalent candidates, so this holds the operator's own guard
    separately: each layer must stand without the other.
    """
    assert list(DropSideEffect().apply(task(reference))) == []
