"""Deeply nested input is refused, never a crash: found by the coverage-guided fuzzer.

Python's JSON and TOML parsers recurse on nesting, and its source parser gives up with
``MemoryError`` on very deep expressions. Every file Bohrin reads may come from someone else (a
results file, a conformance report, a decisions file, a reproduction script, the tests in a
repository ``verify`` is pointed at), so a few kilobytes of brackets must not stop a command with a
traceback. Each entry point is shown refusing it cleanly; ``verify`` lists such a file as not
checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bohrin.cli import CANNOT_RUN, main
from bohrin.decisions import read_decisions
from bohrin.evidence.reproduction import parse_result, script_metadata
from bohrin.history.facts import MAX_DEPTH, facts
from bohrin.ir.task import Task
from bohrin.relations import positive_controls

DEEP = 100_000
ARRAY = "[" * DEEP + "]" * DEEP
OLD = {"tests/test_a.py": "def test_a():\n    assert f(1) == 1\n"}


def test_power_refuses_a_deeply_nested_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "results.jsonl"
    path.write_text('{"task_id": ' + ARRAY + "}\n", encoding="utf-8")
    assert main(["power", str(path)]) == CANNOT_RUN
    assert "nested too deeply" in capsys.readouterr().err


def test_conformance_check_refuses_a_deeply_nested_file(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text(ARRAY, encoding="utf-8")
    assert main(["conformance", "check", str(path)]) == CANNOT_RUN


def test_a_deeply_nested_decisions_file_is_refused() -> None:
    with pytest.raises(ValueError, match="not TOML"):
        read_decisions("x = " + ARRAY)


def test_a_reproduction_scripts_deep_metadata_or_output_is_refused() -> None:
    with pytest.raises(ValueError, match="not TOML"):
        script_metadata("# /// script\n# x = " + ARRAY + "\n# ///\n")
    with pytest.raises(ValueError, match="nested too deeply"):
        parse_result(ARRAY, 0)


@pytest.mark.parametrize(
    "source",
    [
        "def test_a():\n    assert " + "-" * 200_000 + "1\n",
        "def test_a():\n    assert a" + ".b" * DEEP + " == 1\n",
        "def test_a():\n    assert " + "+".join(["1"] * 50_000) + " == 1\n",
        "x = " + "[" * 1000 + "]" * 1000,
    ],
    ids=["unary chain", "attribute chain", "long sum", "nested lists"],
)
def test_verify_lists_a_file_too_deep_to_analyse_as_not_checked(source: str) -> None:
    found, unreadable = facts(OLD, {"tests/test_a.py": source})
    assert unreadable == ["tests/test_a.py"] and found == []


@pytest.mark.parametrize(
    "expression",
    ["a" + ".b" * 1500, "-" * 1500 + "1", "+".join(["1"] * 1500), "not " * 1500 + "y"],
    ids=["attribute chain", "unary chain", "long sum", "not chain"],
)
def test_a_file_that_parses_but_is_too_deep_to_compare_is_not_checked(expression: str) -> None:
    """About 1,500 levels parse, but comparing the trees (``ast.dump``) then exhausts recursion."""
    source = "def test_a():\n    assert " + expression + " == 1\n"
    found, unreadable = facts(OLD, {"tests/test_a.py": source})
    assert unreadable == ["tests/test_a.py"] and found == []


def test_an_ordinary_file_is_nowhere_near_the_depth_limit() -> None:
    """The limit costs nothing real: a long test file with nested data is analysed as usual."""
    tests = (f"def test_n{i}():\n    assert f({i}) == [{i}, ({i}, {{'k': [{i}]}})]\n" for i in range(2000))
    _, unreadable = facts(OLD, {"tests/test_a.py": "import pytest\n\n" + "\n".join(tests)})
    assert unreadable == []
    assert MAX_DEPTH >= 100


def test_positive_controls_skip_a_reference_too_deep_to_parse() -> None:
    reference = "def f(x):\n    return " + "-" * 200_000 + "x\n"
    assert [c.relation for c in positive_controls(Task(id="t", prompt="", reference=reference))] == ["oracle"]
