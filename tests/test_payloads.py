"""Submissions are typed: program text, or changes to a workspace.

A workspace is a template, so the checks here keep it one: every parameter a path names is
declared, no path can leave the root it is applied to, and a candidate cannot change after the
battery has checked it. The battery's rules reach workspaces too, and only operators written
for a task's shape run on it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from _fixtures import REFERENCE, task
from bohrin.ir.task import Candidate, Ground, Payload, Provenance, Shape, Source, Task, Workspace
from bohrin.mutate import discover
from bohrin.mutate.base import MutationOperator
from bohrin.mutate.battery import battery

_HOOK = "{test_root}/conftest.py"

# --------------------------------------------------------------------------- source


def test_surrounding_whitespace_does_not_make_a_different_program() -> None:
    assert Source("  def f(): pass\n").key == Source("def f(): pass").key
    assert Source("def f(): pass").key != Source("def g(): pass").key


# --------------------------------------------------------------------------- workspace


def test_a_workspace_is_the_same_submission_whatever_order_its_files_were_given_in() -> None:
    one = Workspace({"b.py": "", "a.py": None})
    two = Workspace({"a.py": None, "b.py": ""})

    assert one == two and hash(one) == hash(two) and one.key == two.key
    assert list(one.files) == ["a.py", "b.py"]


def test_commands_and_deletions_are_part_of_what_is_submitted() -> None:
    assert Workspace({"a.py": ""}).key != Workspace({"a.py": None}).key
    assert Workspace(commands=("true",)).key != Workspace().key


def test_a_workspace_cannot_change_after_it_is_made() -> None:
    files: dict[str, str | None] = {"a.py": "x = 1\n"}
    workspace = Workspace(files)
    files["a.py"] = "x = 2\n"

    assert workspace.files["a.py"] == "x = 1\n"
    with pytest.raises(TypeError):
        workspace.files["a.py"] = "x = 3\n"  # type: ignore[index]


def test_a_path_may_name_a_declared_parameter() -> None:
    workspace = Workspace({_HOOK: "# hook\n"}, parameters=("test_root",))
    assert _HOOK in workspace.files, "the template is kept as written, never filled in"


@pytest.mark.parametrize(
    ("path", "parameters"),
    [
        ("/etc/passwd", ()),
        ("../outside.py", ()),
        ("tests/../../outside.py", ()),
        ("./a.py", ()),
        ("a//b.py", ()),
        ("", ()),
        ("tests\\test_a.py", ()),
        (_HOOK, ()),
        (_HOOK, ("reward_path",)),
    ],
)
def test_a_path_that_leaves_the_root_or_names_an_undeclared_parameter_is_refused(
    path: str, parameters: tuple[str, ...]
) -> None:
    with pytest.raises(ValueError):
        Workspace({path: ""}, parameters=parameters)


@pytest.mark.parametrize("parameters", [("test root",), ("1st",), ("x", "x")])
def test_parameters_are_distinct_identifiers(parameters: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        Workspace(parameters=parameters)


# --------------------------------------------------------------------------- the battery


class _Proposes(MutationOperator):
    id = "third_party"
    rationale = "test double"

    def __init__(self, *payloads: Payload, shapes: tuple[Shape, ...] = ()) -> None:
        self.payloads = payloads
        self.shapes = shapes

    def apply(self, task: Task) -> Iterator[Candidate]:
        for payload in self.payloads:
            yield Candidate(payload, Provenance(self.id, "constant", "claims it is wrong"), Ground.STRUCTURAL)


_HOLLOW = Workspace({"solution.py": "def solve(items):\n    pass\n"})


def test_only_operators_for_the_tasks_shape_run() -> None:
    container_only = _Proposes(_HOLLOW, shapes=(Shape.CONTAINER,))

    assert battery(task(REFERENCE), [container_only]).candidates == ()
    assert len(battery(task(REFERENCE, shape=Shape.CONTAINER), [container_only]).candidates) == 1


def test_an_operator_that_names_no_shape_runs_on_every_shape() -> None:
    for shape in Shape:
        assert len(battery(task(REFERENCE, shape=shape), [_Proposes(_HOLLOW)]).candidates) == 1, shape


def test_the_built_in_program_operator_does_not_run_on_a_container_task() -> None:
    assert battery(task(REFERENCE, shape=Shape.CONTAINER)).candidates == ()
    assert all(op.shapes for op in discover()), "every built-in operator names its shapes"


def test_a_workspace_that_writes_the_reference_is_suppressed() -> None:
    """It can only remove a ground: a real workspace finding never needs the known-good solution."""
    writes_reference = Workspace({"solution.py": REFERENCE})
    result = battery(task(REFERENCE), [_Proposes(writes_reference, _HOLLOW)])

    assert [c.payload for c in result.candidates] == [_HOLLOW]
    assert result.suppressed == 1


def test_equal_workspaces_are_tried_once() -> None:
    same = Workspace({"solution.py": "def solve(items):\n    pass\n"})
    assert len(battery(task(REFERENCE), [_Proposes(_HOLLOW, same)]).candidates) == 1
