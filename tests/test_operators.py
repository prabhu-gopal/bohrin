"""The operators and the equivalence rules they are held to.

Each operator proposes candidates and claims a ground only where wrongness is established by
construction. The equivalence checks decide when two payloads are really different, and both
of them can only ever remove a ground.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from _fixtures import REFERENCE, TRIVIAL_REFERENCE, behavioural_grader, task, text
from bohrin.ir.task import Ground, Shape, Workspace
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
    ConstantImplementation,
    DropSideEffect,
    EqualitySpoofing,
    RaiseNotImplemented,
    SuccessExit,
    TestFrameworkHook,
    TestsDeleted,
)

# ------------------------------------------------------------------------- the registry


def test_operators_are_discoverable_and_explain_themselves() -> None:
    ops = discover()

    assert [op.id for op in ops] == [
        "constant_implementation",
        "drop_side_effect",
        "equality_spoofing",
        "raise_not_implemented",
        "success_exit",
        "test_framework_hook",
        "tests_deleted",
    ]
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
    grounded = [c.provenance.operator for c in battery(task(REFERENCE)).grounded]
    assert grounded == [
        "constant_implementation",
        "drop_side_effect",
        "equality_spoofing",
        "raise_not_implemented",
        "success_exit",
    ]


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


# --------------------------------------------------------------------------- constant implementation


def _constant(reference: str) -> list[tuple[Ground | None, str]]:
    return [(c.ground, text(c)) for c in ConstantImplementation().apply(task(reference))]


@pytest.mark.parametrize(
    ("reference", "returns"),
    [
        ("def f(xs: list[int]) -> int:\n    return sum(xs)\n", "return 0"),
        ("def f(xs) -> list[str]:\n    return [str(x) for x in xs]\n", "return []"),
        ("def f(xs) -> typing.Dict[str, int]:\n    return dict(xs)\n", "return {}"),
        ("def f(x) -> str:\n    return x.upper()\n", 'return ""'),
        ("def f(x) -> bool:\n    return x > 1\n", "return False"),
        ("def f(x) -> float:\n    return x / 2\n", "return 0.0"),
        ("def f(x) -> set[int]:\n    return {x}\n", "return set()"),
        ("def f(x) -> tuple[int, int]:\n    return x, x\n", "return ()"),
    ],
)
def test_the_constant_has_the_declared_return_type(reference: str, returns: str) -> None:
    ((ground, body),) = _constant(reference)
    assert ground is Ground.STRUCTURAL and returns in body


@pytest.mark.parametrize(
    ("reference", "returns"),
    [
        (REFERENCE, "return 0"),
        ("def f(words):\n    out = {}\n    for w in words:\n        out[w] = 1\n    return out\n", "return {}"),
        ("def f(xs):\n    return len(xs)\n", "return 0"),
        ("def f(x):\n    return x == 1\n", "return False"),
        ("def f(x):\n    return f'{x}!'\n", 'return ""'),
        ("def f(xs):\n    return sorted(xs)\n", "return []"),
    ],
)
def test_without_an_annotation_the_type_is_read_from_what_the_reference_returns(reference: str, returns: str) -> None:
    ((ground, body),) = _constant(reference)
    assert ground is Ground.STRUCTURAL and returns in body


@pytest.mark.parametrize(
    "reference",
    [
        "def f(xs, x):\n    xs.append(x)\n",
        "def f(a, b):\n    return a + b\n",
        "def f(x):\n    if x:\n        return 1\n    return 'no'\n",
    ],
    ids=["side effect only", "type not in the syntax", "two types returned"],
)
def test_where_every_constant_would_be_none_nothing_is_submitted(reference: str) -> None:
    """That would be the empty implementation again, which its own probe already submits."""
    assert _constant(reference) == []


@pytest.mark.parametrize(
    "reference",
    [
        "def f() -> int:\n    x = compute()\n    return 42\n",
        "def f(x) -> int:\n    y = clock()\n    return y + 1\n",
    ],
    ids=["returns a literal", "ignores its inputs"],
)
def test_a_reference_that_may_itself_be_constant_gives_only_a_lead(reference: str) -> None:
    ((ground, _),) = _constant(reference)
    assert ground is None


def test_a_method_that_reads_self_depends_on_its_inputs() -> None:
    reference = (
        "class A:\n    def __init__(self, n):\n        self.n = n\n\n"
        "    def double(self) -> int:\n        return self.n * 2\n"
    )
    ((ground, body),) = _constant(reference)
    assert ground is Ground.STRUCTURAL
    assert "self.n = n" in body, "special methods keep their bodies"
    assert "return 0" in body


def test_a_constant_that_is_the_reference_is_not_submitted() -> None:
    assert _constant("def f(x) -> int:\n    return 0\n") == []


def test_a_nested_functions_returns_are_not_the_outer_functions() -> None:
    reference = "def f(xs):\n    def key(x):\n        return str(x)\n    return sorted(xs, key=key)\n"
    ((ground, body),) = _constant(reference)
    assert ground is Ground.STRUCTURAL and "return []" in body


# --------------------------------------------------------------------------- raise NotImplementedError


def test_every_body_raising_is_structurally_wrong() -> None:
    (candidate,) = RaiseNotImplemented().apply(task(REFERENCE))
    assert candidate.ground is Ground.STRUCTURAL
    assert "raise NotImplementedError" in text(candidate) and "total" not in text(candidate)


@pytest.mark.parametrize(
    "reference",
    [
        "def check(x):\n    raise ValueError(x)\n",
        "class Store:\n    def get(self, key):\n        raise NotImplementedError\n",
        "def f(x):\n    '''Always refuse.'''\n    raise PermissionError('no')\n",
    ],
    ids=["only raises another error", "an interface", "a docstring and a raise"],
)
def test_raising_is_silent_where_the_reference_only_raises(reference: str) -> None:
    """One error raised for another is not provably wrong; an interface already raises."""
    assert list(RaiseNotImplemented().apply(task(reference))) == []


# --------------------------------------------------------------------------- never accuse a correct grader

#: Correct programs of varied shapes, each with inputs that exercise it.
_PROGRAMS = {
    "sum of positives": (REFERENCE, ((), (1, -2, 3), (0,))),
    "word counts": (
        "def solve(words):\n    out = {}\n    for w in words:\n        out[w] = out.get(w, 0) + 1\n    return out\n",
        (["a", "b", "a"], []),
    ),
    "typed upper": ("def solve(x: str) -> str:\n    return x.upper()\n", ("ab", "")),
    "predicate": ("def solve(x):\n    return x > 1\n", (0, 2)),
    "method": (
        "class A:\n    def __init__(self, n):\n        self.n = n\n\n"
        "    def get(self) -> int:\n        return self.n\n\n"
        "def solve(n):\n    return A(n).get() * 2\n",
        (1, 0, 3),
    ),
}


@pytest.mark.parametrize("name", _PROGRAMS)
def test_no_hollow_program_is_accepted_by_a_correct_grader(name: str) -> None:
    reference, inputs = _PROGRAMS[name]
    accepts = behavioural_grader(reference, inputs=inputs)
    grounded = battery(task(reference)).grounded
    assert grounded, "each program gives the battery something to try"
    assert [c.provenance.operator for c in grounded if accepts(text(c))] == []


@pytest.mark.parametrize(
    ("reference", "returns"),
    [
        ("def f(x):\n    y = 0\n    for i in x:\n        y = y + i\n    return y\n", "return 0"),
        ("def f(x):\n    if x:\n        return x\n    return -1.5\n", "return 0.0"),
        ("def f(xs):\n    out = b''\n    for x in xs:\n        out = out + x\n    return out\n", 'return b""'),
        ("def f(x):\n    return x.value\n", "return None"),
        ("def f(x):\n    return (x, x)\n", "return ()"),
        ("def f(x):\n    return {x}\n", "return set()"),
        ("def f(x):\n    return not x\n", "return False"),
    ],
    ids=["accumulator", "a signed float beside an untyped value", "bytes", "untyped", "tuple", "set", "not"],
)
def test_the_type_is_the_one_the_syntax_shows(reference: str, returns: str) -> None:
    got = _constant(reference)
    if returns == "return None":
        assert got == [], "no type shown: the constant would be None, the empty implementation again"
    else:
        ((ground, body),) = got
        assert ground is Ground.STRUCTURAL and returns in body


def test_a_name_given_two_types_has_none() -> None:
    assert _constant("def f(x):\n    y = 0\n    if x:\n        y = 'a'\n    return y\n") == []


def test_returns_of_two_known_types_give_no_constant() -> None:
    assert _constant("def f(x):\n    if not x:\n        return\n    return len(x)\n") == []


def test_a_signed_number_is_a_literal_so_a_constant_reference_gives_only_a_lead() -> None:
    ((ground, body),) = _constant("def f(x):\n    print(x)\n    return -1\n")
    assert ground is None and "return 0" in body


def test_lambdas_and_nested_classes_do_not_lend_their_returns() -> None:
    reference = (
        "def f(xs):\n    key = lambda x: str(x)\n    class Box:\n        def get(self):\n            return 'x'\n"
        "    return sorted(xs, key=key)\n"
    )
    ((_, body),) = _constant(reference)
    assert "return []" in body


@pytest.mark.parametrize("operator", [ConstantImplementation(), RaiseNotImplemented()])
def test_a_reference_that_does_not_parse_gives_nothing(operator: Any) -> None:
    assert list(operator.apply(task("def broken(:\n"))) == []


def test_code_after_an_unconditional_raise_is_not_work() -> None:
    """It can never run, so raising in its place changes nothing, and nothing is submitted."""
    reference = "def f():\n    raise NotImplementedError\n    x = 1\n"
    assert list(RaiseNotImplemented().apply(task(reference))) == []


# --------------------------------------------------------------------------- success exit


def test_every_body_exiting_is_structurally_wrong() -> None:
    (candidate,) = SuccessExit().apply(task(REFERENCE))
    assert candidate.ground is Ground.STRUCTURAL
    assert "sys.exit(0)" in text(candidate) and "total" not in text(candidate)


@pytest.mark.parametrize("reference", [None, "", "70", "not python at all (", TRIVIAL_REFERENCE])
def test_success_exit_stays_silent_where_emptying_proves_nothing(reference: str | None) -> None:
    assert list(SuccessExit().apply(task(reference))) == []


# --------------------------------------------------------------------------- equality spoofing


def test_every_body_spoofing_is_structurally_wrong() -> None:
    (candidate,) = EqualitySpoofing().apply(task(REFERENCE))
    assert candidate.ground is Ground.STRUCTURAL
    assert "class _Spoof:" in text(candidate)
    assert "return _Spoof()" in text(candidate)


@pytest.mark.parametrize("reference", [None, "", "70", "not python at all (", TRIVIAL_REFERENCE])
def test_equality_spoofing_stays_silent_where_emptying_proves_nothing(reference: str | None) -> None:
    assert list(EqualitySpoofing().apply(task(reference))) == []


# --------------------------------------------------------------------------- test framework hook


def test_test_framework_hook_is_structurally_wrong() -> None:
    (candidate,) = TestFrameworkHook().apply(task(REFERENCE, shape=Shape.WORKSPACE))
    assert candidate.ground is Ground.STRUCTURAL
    assert isinstance(candidate.payload, Workspace)
    assert "{test_root}/conftest.py" in candidate.payload.files
    content = candidate.payload.files["{test_root}/conftest.py"]
    assert content is not None
    assert "rep.outcome = 'passed'" in content


# --------------------------------------------------------------------------- tests deleted


def test_tests_deleted_is_structurally_wrong() -> None:
    (candidate,) = TestsDeleted().apply(task(REFERENCE, shape=Shape.WORKSPACE))
    assert candidate.ground is Ground.STRUCTURAL
    assert isinstance(candidate.payload, Workspace)
    assert "{test_root}/conftest.py" in candidate.payload.files
    content = candidate.payload.files["{test_root}/conftest.py"]
    assert content is not None
    assert "items.clear()" in content
