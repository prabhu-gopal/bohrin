"""How strongly a test checks what it runs, and the ways a change can make it check less.

A test's *oracle* is what decides pass or fail. Counting assertions misses the commonest way an
oracle gets weaker: the count stays the same while ``assert parse(x) == 5`` becomes
``assert parse(x) is not None``. So each test's checks are classified with the taxonomy of
*All Smoke, No Alarm* (arXiv:2606.18168), which found 80.2% of 86,156 agent-authored test patches
carried weak or no oracle signals:

====  ================================================  ========
S1    value equality or comparison                      strong
S2    an error, containment or type check               strong
S3    two or more distinct strong kinds                 strong
W1    no assertion                                      weak
W2    existence or non-null checks only                 weak
W3    boolean assertions only (no value compared)       weak
W4    mock or call verification only                    weak
W5    snapshot match only                               weak
====  ================================================  ========

Beside strength, a test can be made easier to pass without touching its assertions: a numeric
tolerance loosened, a timeout raised, a check wrapped in ``try``/``except`` that swallows its
failure, an expected value rewritten, or the function the test is named after replaced by a mock
(the "mockery" anti-pattern; agents add mocks in 36% of test commits against 26% for people,
Hora, MSR 2026, arXiv:2602.00409). Each is read from syntax trees; nothing is run.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator

Test = ast.FunctionDef | ast.AsyncFunctionDef

STRONG = ("S3", "S1", "S2")
WEAK = ("W5", "W4", "W3", "W2", "W1")

_VALUE_METHODS = frozenset(
    {
        "assertEqual",
        "assertNotEqual",
        "assertAlmostEqual",
        "assertNotAlmostEqual",
        "assertGreater",
        "assertGreaterEqual",
        "assertLess",
        "assertLessEqual",
        "assertListEqual",
        "assertDictEqual",
        "assertTupleEqual",
        "assertSetEqual",
        "assertSequenceEqual",
        "assertCountEqual",
        "assertMultiLineEqual",
        "assert_allclose",
        "assert_array_equal",
        "assert_array_almost_equal",
        "assert_equal",
        "assert_frame_equal",
        "assert_series_equal",
    }
)
_STRONG_OTHER_METHODS = frozenset(
    {
        "assertRaises",
        "assertRaisesRegex",
        "assertWarns",
        "assertWarnsRegex",
        "assertIn",
        "assertNotIn",
        "assertIsInstance",
        "assertNotIsInstance",
        "assertRegex",
        "assertNotRegex",
    }
)
_EXISTENCE_METHODS = frozenset({"assertIsNotNone", "assertIsNone"})
_BOOLEAN_METHODS = frozenset({"assertTrue", "assertFalse"})

#: Tolerance arguments, and their defaults when a call leaves them out.
_TOLERANCES = {
    "approx": {"rel": 1e-6, "abs": 1e-12},
    "isclose": {"rel_tol": 1e-9, "abs_tol": 0.0},
    "assert_allclose": {"rtol": 1e-7, "atol": 0.0},
    "allclose": {"rtol": 1e-5, "atol": 1e-8},
    "assertAlmostEqual": {"delta": 0.0},
}


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = _dotted(node.value)
        return f"{inner}.{node.attr}" if inner else node.attr
    return ""


def _leaf(node: ast.AST) -> str:
    return _dotted(node).rsplit(".", 1)[-1]


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _kind_of_assert(test: ast.expr) -> str:
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        op, right = test.ops[0], test.comparators[0]
        if isinstance(op, ast.Is | ast.IsNot) and _is_none(right):
            return "W2"
        if isinstance(op, ast.In | ast.NotIn):
            return "S2"
        if "snapshot" in ast.dump(right).lower() or "snapshot" in ast.dump(test.left).lower():
            return "W5"
        return "S1"
    if isinstance(test, ast.Compare):
        return "S1"
    if isinstance(test, ast.Call) and _leaf(test.func) in ("isinstance", "issubclass"):
        return "S2"
    if isinstance(test, ast.Attribute) and test.attr in ("called", "called_once"):
        return "W4"
    return "W3"


def _kind_of_call(call: ast.Call) -> str | None:
    name = _leaf(call.func)
    full = _dotted(call.func)
    if name in _VALUE_METHODS:
        return "S1"
    if name in _STRONG_OTHER_METHODS or full in ("pytest.raises", "pytest.warns"):
        return "S2"
    if name in _EXISTENCE_METHODS:
        return "W2"
    if name in _BOOLEAN_METHODS:
        return "W3"
    if name.startswith("assert_called") or name in ("assert_not_called", "assert_any_call", "assert_has_calls"):
        return "W4"
    if "snapshot" in name.lower():
        return "W5"
    return None


def check_kinds(test: Test) -> set[str]:
    """The oracle categories of every check in ``test``."""
    kinds: set[str] = set()
    for node in ast.walk(test):
        if isinstance(node, ast.Assert):
            kinds.add(_kind_of_assert(node.test))
        elif isinstance(node, ast.Call):
            kind = _kind_of_call(node)
            if kind:
                kinds.add(kind)
    return kinds


def strength(test: Test) -> str:
    """The test's oracle category: its strongest checks, or W1 when it has none."""
    kinds = check_kinds(test)
    strong = {kind for kind in kinds if kind in ("S1", "S2")}
    if len(strong) >= 2:
        return "S3"
    if strong:
        return strong.pop()
    for kind in ("W5", "W4", "W3", "W2"):
        if kind in kinds:
            return kind
    return "W1"


DESCRIPTIONS = {
    "S1": "value equality or comparison",
    "S2": "an error, containment or type check",
    "S3": "value and error, containment or type checks",
    "W1": "no assertion",
    "W2": "a non-None check only",
    "W3": "a truth check only, comparing no value",
    "W4": "mock-call verification only",
    "W5": "a snapshot match only",
}


def _number(node: ast.AST) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float) and not isinstance(node.value, bool):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _number(node.operand)
        return None if inner is None else -inner
    return None


def tolerances(test: Test) -> dict[str, float]:
    """The loosest tolerance of each kind a test grants, keyed ``function.argument``.

    An argument left out counts at its documented default, so adding ``rel=0.5`` to an ``approx``
    that had none is a loosening. ``assertAlmostEqual``'s ``places`` is turned into the tolerance
    it grants, ``10 ** -places``, so fewer places is a larger number, like every other entry.
    """
    loosest: dict[str, float] = {}
    for node in ast.walk(test):
        if not isinstance(node, ast.Call):
            continue
        name = _leaf(node.func)
        if name not in _TOLERANCES:
            continue
        given = {kw.arg: _number(kw.value) for kw in node.keywords if kw.arg}
        for argument, default in _TOLERANCES[name].items():
            value = given.get(argument)
            key = f"{name}.{argument}"
            loosest[key] = max(loosest.get(key, 0.0), default if value is None else value)
        if name == "assertAlmostEqual":
            places = given.get("places")
            if places is None and len(node.args) >= 3:
                places = _number(node.args[2])
            tolerance = 10.0 ** -(7 if places is None else places)
            loosest["assertAlmostEqual.places"] = max(loosest.get("assertAlmostEqual.places", 0.0), tolerance)
    return loosest


def timeouts(test: Test) -> float:
    """The largest timeout a test or its decorators set (``@pytest.mark.timeout(n)``, ``timeout=n``)."""
    largest = 0.0
    nodes: Iterator[ast.AST] = ast.walk(test)
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        if _leaf(node.func) == "timeout" and node.args:
            value = _number(node.args[0])
            if value is not None:
                largest = max(largest, value)
        for keyword in node.keywords:
            if keyword.arg == "timeout":
                value = _number(keyword.value)
                if value is not None:
                    largest = max(largest, value)
    return largest


def expected_values(test: Test) -> dict[str, str]:
    """The literal each checked expression is compared with, keyed by the expression's syntax tree."""
    found: dict[str, str] = {}
    for node in ast.walk(test):
        if isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare) and len(node.test.ops) == 1:
            if isinstance(node.test.ops[0], ast.Eq) and isinstance(node.test.comparators[0], ast.Constant):
                found[ast.dump(node.test.left)] = repr(node.test.comparators[0].value)
        elif isinstance(node, ast.Call) and _leaf(node.func) == "assertEqual" and len(node.args) >= 2:
            first, second = node.args[0], node.args[1]
            if isinstance(second, ast.Constant):
                found[ast.dump(first)] = repr(second.value)
    return found


def _catches_failures(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(_leaf(t) in ("AssertionError", "Exception", "BaseException") for t in types)


def swallowed_checks(test: Test) -> int:
    """Checks inside a ``try`` whose handler catches ``AssertionError``, so their failure is silenced."""
    count = 0
    for node in ast.walk(test):
        if isinstance(node, ast.Try) and any(_catches_failures(h) for h in node.handlers):
            for inner in node.body:
                for child in ast.walk(inner):
                    count += isinstance(child, ast.Assert) or (
                        isinstance(child, ast.Call) and _kind_of_call(child) is not None
                    )
    return count


_WORDS = re.compile(r"[a-z0-9]+")


def mocked_subjects(test: Test) -> set[str]:
    """Names a test patches that are also words of its own name: the mock may be the thing tested.

    ``test_parse_header`` patching ``pkg.parse_header`` or ``pkg.parse`` is testing its mock.
    Patches of dependencies (``requests.get`` in ``test_parse_header``) are not reported.
    """
    name = test.name.removeprefix("test").strip("_").lower()
    words = set(_WORDS.findall(name))
    if not name:
        return set()
    found: set[str] = set()
    for node in ast.walk(test):
        if not isinstance(node, ast.Call):
            continue
        callee = _dotted(node.func)
        target = ""
        if _leaf(node.func) in ("patch", "setattr") and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                target = first.value.rsplit(".", 1)[-1]
            elif len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                target = node.args[1].value
        elif callee.endswith("patch.object") and len(node.args) >= 2:
            second = node.args[1]
            if isinstance(second, ast.Constant) and isinstance(second.value, str):
                target = second.value
        target = target.lower()
        if target and (target == name or target in words or all(w in words for w in _WORDS.findall(target))):
            found.add(target)
    return found


__all__ = [
    "DESCRIPTIONS",
    "STRONG",
    "WEAK",
    "check_kinds",
    "expected_values",
    "mocked_subjects",
    "strength",
    "swallowed_checks",
    "timeouts",
    "tolerances",
]
