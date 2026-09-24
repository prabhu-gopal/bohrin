"""Positive controls: every rewriting emitted does exactly what the original does.

A wrong positive control would accuse a correct grader of rejecting correct code, so each rewriting
is emitted only with a mechanical certificate. These tests check the certificates from outside: they
run every emitted control beside its original, on a corpus of programs chosen to break naive
renaming (globals, closures, generators, exceptions, async code, f-strings, reflection), and demand
identical results. They also hold the two directions every probe is held to: a correct grader
accepts every control, and a grader that is too narrow is caught.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import pytest

from _fixtures import REFERENCE, behavioural_grader, task
from bohrin.relations import BASELINE, discover, positive_controls
from bohrin.relations.builtin import CommentFree, Reformatted, RenamedLocals
from bohrin.relations.certify import same_bytecode_except_local_names, same_syntax

#: Programs, and inputs to call their ``solve`` with.
CORPUS: dict[str, tuple[str, tuple[Any, ...]]] = {
    "loop and branch": (REFERENCE, ([1, -2, 3], [], [0, 5])),
    "comments everywhere": (
        "# a module comment\ndef solve(n):  # doubles\n    result = n * 2  # the work\n    return result\n",
        (0, 3, -4),
    ),
    "global read beside a local": (
        "SCALE = 3\n\ndef solve(n):\n    base = n + 1\n    return base * SCALE\n",
        (0, 2, 10),
    ),
    "exception name and handler": (
        "def solve(text):\n    try:\n        value = int(text)\n    except ValueError as error:\n"
        "        value = len(str(error))\n    return value\n",
        ("12", "x", ""),
    ),
    "generator": (
        "def solve(n):\n    total = 0\n    def gen():\n        yield 1\n    for item in range(n):\n"
        "        total += item\n    return total\n",
        (0, 4),
    ),
    "walrus and while": (
        "def solve(items):\n    found = []\n    index = 0\n    while (index := index + 1) < len(items):\n"
        "        found.append(items[index])\n    return found\n",
        ([1, 2, 3], [], [5]),
    ),
    "f-string with a name specifier": ("def solve(n):\n    value = n + 1\n    return f'{value=}'\n", (1, 2)),
    "reads its own locals": ("def solve(n):\n    value = n\n    return sorted(locals())\n", (1,)),
    "class with methods": (
        "class Acc:\n    def __init__(self):\n        self.items = []\n    def add(self, x):\n        doubled = x * 2\n"
        "        self.items.append(doubled)\n        return self\n\ndef solve(n):\n    acc = Acc()\n"
        "    for step in range(n):\n        acc.add(step)\n    return acc.items\n",
        (0, 3),
    ),
    "decorated": (
        "import functools\n\n@functools.lru_cache(maxsize=None)\ndef solve(n):\n    result = 1\n"
        "    for k in range(1, n + 1):\n        result *= k\n    return result\n",
        (0, 5),
    ),
    "async": (
        "import asyncio\n\nasync def inner(x):\n    bumped = x + 1\n    return bumped\n\n"
        "def solve(n):\n    return asyncio.run(inner(n))\n",
        (1, 9),
    ),
}


def _outcome(source: str, inputs: tuple[Any, ...]) -> list[tuple[str, str]]:
    namespace: dict[str, Any] = {}
    exec(compile(source, "<corpus>", "exec"), namespace)
    solve: Callable[[Any], Any] = namespace["solve"]
    results = []
    for value in inputs:
        try:
            out = solve(value)
            results.append((type(out).__name__, repr(out)))
        except Exception as exc:
            results.append(("raised", type(exc).__name__))
    return results


@pytest.mark.parametrize("name", CORPUS)
def test_every_emitted_control_behaves_exactly_like_its_original(name: str) -> None:
    source, inputs = CORPUS[name]
    expected = _outcome(source, inputs)
    for control in positive_controls(task(source)):
        assert _outcome(control.payload.text, inputs) == expected, f"{control.relation} changed {name}"
    asyncio.set_event_loop_policy(None)


@pytest.mark.parametrize(
    "name", ["f-string with a name specifier", "reads its own locals", "generator", "global read beside a local"]
)
def test_renaming_is_refused_or_certified_where_names_matter(name: str) -> None:
    """The four traps for renaming: each is refused, or renamed with a certificate that still holds."""
    source, inputs = CORPUS[name]
    rewritten = RenamedLocals().render(source)
    if rewritten is not None:
        assert same_bytecode_except_local_names(source, rewritten)
        assert _outcome(rewritten, inputs) == _outcome(source, inputs)


def test_code_that_reads_its_own_locals_is_never_renamed() -> None:
    assert RenamedLocals().render(CORPUS["reads its own locals"][0]) is None


def test_an_f_string_name_specifier_keeps_its_output_when_renamed() -> None:
    """``f"{value=}"`` prints ``value=``: Python stores that label as a constant when it compiles, so
    renaming the variable leaves the output unchanged, and the certificate correctly allows it."""
    source, inputs = CORPUS["f-string with a name specifier"]
    rewritten = RenamedLocals().render(source)
    assert rewritten is not None and "value=" in rewritten
    assert _outcome(rewritten, inputs) == _outcome(source, inputs)


def test_parameters_and_function_names_are_kept() -> None:
    rewritten = RenamedLocals().render(REFERENCE)
    assert rewritten is not None and "def solve(items):" in rewritten and "total" not in rewritten


# --------------------------------------------------------------------------- the certificates


@pytest.mark.parametrize(
    ("left", "right", "syntax", "bytecode"),
    [
        ("x = 1\n", "x=1  # set\n", True, True),
        ("def f(a):\n    b = a\n    return b\n", "def f(a):\n    c = a\n    return c\n", False, True),
        ("def f(a):\n    b = a\n    return b\n", "def f(z):\n    b = z\n    return b\n", False, False),
        ("def f(a):\n    return a + 1\n", "def f(a):\n    return a - 1\n", False, False),
        (
            "n = 1\ndef f():\n    k = 2\n    return k + n\n",
            "n = 1\ndef f():\n    n = 2\n    return n + n\n",
            False,
            False,
        ),
    ],
    ids=["layout", "local renamed", "parameter renamed", "real change", "clash with a global"],
)
def test_each_certificate_proves_only_what_it_says(left: str, right: str, syntax: bool, bytecode: bool) -> None:
    assert same_syntax(left, right) is syntax
    assert same_bytecode_except_local_names(left, right) is bytecode


# --------------------------------------------------------------------------- the controls


def test_the_baseline_comes_first_and_nothing_without_a_reference() -> None:
    controls = positive_controls(task(REFERENCE))
    assert controls[0].relation == BASELINE and controls[0].payload.text == REFERENCE
    assert all(not c.baseline for c in controls[1:])
    assert positive_controls(task(None)) == ()


def test_no_control_repeats_another() -> None:
    texts = [c.payload.text.strip() for c in positive_controls(task(CORPUS["comments everywhere"][0]))]
    assert len(texts) == len(set(texts))


def test_the_built_in_relations_are_discovered_in_catalogue_order() -> None:
    assert [r.id for r in discover()] == ["comment_free", "reformatted", "renamed_locals"]
    assert all(r.certification for r in discover())


def test_a_correct_grader_accepts_every_control() -> None:
    """The mirror of the battery's guard: no positive control may be rejected by a correct grader."""
    accepts = behavioural_grader(REFERENCE, inputs=((), (1, -2, 3), (0,)))
    assert all(accepts(c.payload.text) for c in positive_controls(task(REFERENCE)))


def test_a_grader_too_narrow_for_correct_code_is_caught() -> None:
    """A grader that accepts only the reference's exact text rejects correct rewritings (BGW-120)."""
    rejected = [c.relation for c in positive_controls(task(REFERENCE)) if c.payload.text != REFERENCE]
    assert rejected, "a narrow grader must reject at least one correct control"


@pytest.mark.parametrize("relation", [CommentFree(), Reformatted(), RenamedLocals()])
def test_a_relation_is_silent_on_code_that_does_not_parse(relation: Any) -> None:
    assert relation.render("def broken(:\n") is None


def test_a_rewriting_that_only_adds_blank_lines_is_not_a_second_control(monkeypatch: pytest.MonkeyPatch) -> None:
    """Surrounding blank lines are not a different program; a relation adding them adds no control."""
    import bohrin.relations as relations
    from bohrin.relations.base import Relation

    class Padded(Relation):
        certification = "test double"

        def render(self, answer: str) -> str | None:
            return "\n\n" + answer + "\n\n"

    monkeypatch.setattr(relations, "load_plugin_classes", lambda group: {"padded": Padded})
    assert [c.relation for c in positive_controls(task(REFERENCE))] == [BASELINE]
