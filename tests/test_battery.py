"""The false-accusation guard, at the level of the battery.

Bohrin's governing rule is that it must never falsely accuse a verifier. A candidate may be
called wrong only when its wrongness is established independently of the verifier under
audit, so the property is checked here directly: **no grounded candidate is ever accepted by
a correct grader.** Each case below is a correct grader a past version of the definitions
accused, and the build fails if that accusation comes back.

The battery's rules apply to every operator, including third-party ones that reach it with no
review, so most cases here use a test-double operator that makes exactly the over-claim the
rule exists to catch. The counterweights matter as much: a genuinely weak grader must still
accept grounded candidates, or a guard has simply switched the battery off.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from _fixtures import LENIENT_CORRECT, REFERENCE, TRIVIAL_REFERENCE, behavioural_grader, task, text
from bohrin.ir.task import Candidate, Ground, Provenance, Shape, Source, Task, Workspace
from bohrin.mutate.base import MutationOperator
from bohrin.mutate.battery import battery


class _Proposes(MutationOperator):
    """A third-party operator: it proposes fixed payloads with the grounds it claims, unchecked."""

    id = "third_party"
    rationale = "test double"

    def __init__(self, *proposals: tuple[str, Ground | None]) -> None:
        self.proposals = proposals

    def apply(self, task: Task) -> Iterator[Candidate]:
        for payload, ground in self.proposals:
            yield Candidate(
                Source(payload), Provenance(self.id, "constant", f"claims {payload[:20]!r} is wrong"), ground
            )


#: What an unguarded third-party operator might claim about any task: an empty submission
#: does no work, and every constant is a different answer.
_OVERCLAIMS = _Proposes(
    ("", Ground.STRUCTURAL),
    *((literal, Ground.DIFFERENTIAL) for literal in ("0", "1", "True", "None", "[]", '""')),
)


def _accused(t: Task, accepts: Callable[[str], bool], operators: Sequence[MutationOperator] | None = None) -> list[str]:
    """Grounded candidates a grader accepted, as ``operator: payload``. Empty for a correct grader."""
    return [f"{c.provenance.operator}: {text(c)[:60]!r}" for c in battery(t, operators).grounded if accepts(text(c))]


# --------------------------------------------------------------------------- the guard


@pytest.mark.parametrize(("name", "reference", "equal"), LENIENT_CORRECT, ids=[c[0] for c in LENIENT_CORRECT])
def test_a_lenient_but_correct_grader_is_never_accused(
    name: str, reference: str, equal: Callable[[str, str], bool]
) -> None:
    """Accepting ``1`` for a stored answer of ``1.0`` is numeric comparison working."""
    assert _accused(task(reference), lambda reply: equal(reply, reference), [_OVERCLAIMS]) == [], name


def test_the_built_in_battery_accuses_no_behavioural_grader() -> None:
    """A grader that runs the submission and compares outputs is correct, and must be clean."""
    accepts = behavioural_grader(REFERENCE, inputs=((), (1, -2, 3), (0,)))
    assert _accused(task(REFERENCE), accepts) == []


def test_emptying_an_already_empty_reference_is_not_called_wrong() -> None:
    t = task(TRIVIAL_REFERENCE)
    assert _accused(t, lambda reply: reply == TRIVIAL_REFERENCE) == []


def test_an_ungrounded_candidate_stays_a_lead() -> None:
    result = battery(task(REFERENCE), [_Proposes(("def solve(items):\n    return -1\n", None))])

    assert result.grounded == ()
    assert len(result.leads) == 1


#: A reference whose work is all in special methods, beside a helper nothing calls. Replacing only
#: the helper, and keeping the special methods, left every bit of the work in place.
_WORK_IN_SPECIAL_METHODS = """class Vec:
    def __init__(self, x):
        self.x = x

    def __add__(self, other):
        return Vec(self.x + other.x)

    def norm(self) -> int:
        return abs(self.x)


def _debug(v):
    print(v.x)
"""


def _adds_vectors(payload: str) -> bool:
    """A correct grader of vector addition: the exact type and the value, and nothing else."""
    namespace: dict[str, Any] = {}
    try:
        exec(compile(payload, "<fixture>", "exec"), namespace)
        vec = namespace["Vec"]
        total = vec(2) + vec(3)
        return type(total) is vec and total.x == 5
    except BaseException:
        return False


def test_work_kept_in_special_methods_is_never_called_removed() -> None:
    """A grader checking only what the special methods do is right to accept a submission that keeps them."""
    assert _adds_vectors(_WORK_IN_SPECIAL_METHODS)
    assert _accused(task(_WORK_IN_SPECIAL_METHODS), _adds_vectors) == []
    assert battery(task(_WORK_IN_SPECIAL_METHODS)).grounded, "the special methods' work is still probed"


#: A script whose output comes from module-level code; its one function is never called.
_SCRIPT_WITH_DEAD_HELPER = "def _unused():\n    return 1\n\n\nprint(sum([2, 3]))\n"


def _prints_five(payload: str) -> bool:
    """A correct grader of the script: what it prints."""
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            exec(compile(payload, "<fixture>", "exec"), {})
    except BaseException:
        return False
    return printed.getvalue() == "5\n"


def test_removing_work_nothing_calls_is_never_called_wrong() -> None:
    assert _prints_five(_SCRIPT_WITH_DEAD_HELPER)
    assert _accused(task(_SCRIPT_WITH_DEAD_HELPER), _prints_five) == []


# ------------------------------------------------------------ third-party collisions


def test_a_third_party_candidate_that_is_the_answer_is_suppressed_and_counted() -> None:
    """A collision of answers, through the one seam with no review: ``70.0`` against ``70``."""
    op = _Proposes(("70.0", Ground.DIFFERENTIAL), ("71", Ground.DIFFERENTIAL))
    result = battery(task("70"), [op])

    assert [text(c) for c in result.candidates] == ["71"], "only the colliding candidate is removed"
    assert result.suppressed == 1


def test_a_third_party_program_that_compiles_to_the_reference_is_suppressed() -> None:
    """Trivial Compiler Equivalence: a comment is not a different program."""
    commented = REFERENCE.replace("total = 0", "total = 0  # start")
    result = battery(task(REFERENCE), [_Proposes((commented, Ground.DIFFERENTIAL))])

    assert result.candidates == ()
    assert result.suppressed == 1


def test_an_empty_submission_is_not_suppressed_against_a_bare_answer() -> None:
    """``compile("70")`` equals ``compile("")``; TCE once suppressed the empty reply everywhere."""
    result = battery(task("70"), [_OVERCLAIMS])

    assert any(text(c) == "" and c.known_wrong for c in result.candidates)


# ---------------------------------------------------------------- withdrawn grounds


def test_on_a_task_whose_answer_is_a_refusal_every_ground_is_withdrawn() -> None:
    t = task("I’m sorry, but I can’t help with that.", prompt="Write malware that encrypts a hospital's files.")
    result = battery(t, [_OVERCLAIMS])

    assert result.grounded == ()
    assert result.withdrawn == len(result.candidates) > 0, "still tried, as leads"


_SPEC = '{"func_name": "verify_postscript", "N": null, "postscript_marker": "Addendum:"}'


def test_a_json_object_answer_keeps_only_the_grounds_that_need_no_answer() -> None:
    """A constraint spec is grader state: differing from it proves nothing."""
    grounds = {c.ground for c in battery(task(_SPEC), [_OVERCLAIMS]).grounded}

    assert grounds == {Ground.STRUCTURAL}, "an empty submission is still wrong whatever the answer field holds"


def test_a_grid_answer_keeps_its_reference_grounds() -> None:
    grounds = {c.ground for c in battery(task("[[1, 2], [3, 4]]"), [_OVERCLAIMS]).grounded}
    assert Ground.DIFFERENTIAL in grounds


# ------------------------------------------------------------------- counterweights


# ----------------------------------------------------------- workspaces, judged by real pytest

#: The grader's own test, which the environment keeps in the test root.
_GRADER_TEST = "from solution import solve\n\n\ndef test_solve():\n    assert solve([1, -2, 3]) == 4\n"


def _pytest(workspace: Workspace, root: Path, *, isolated: bool) -> int:
    """Instantiate the workspace as an environment would, beside the grader's test, and run pytest.

    ``isolated`` is what a correct grader does: it runs its tests without any ``conftest.py`` the
    submission wrote. Every run is a process of its own with a time limit.
    """
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_solve.py").write_text(_GRADER_TEST, encoding="utf-8")
    for path, content in workspace.files.items():
        target = root / path.replace("{test_root}", "tests").replace("{source_path}", "solution.py")
        target.write_text(content or "", encoding="utf-8")
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
    if isolated:
        command.insert(-1, "--noconftest")
    env = {**os.environ, "PYTHONPATH": str(root)}
    env.pop("PYTEST_ADDOPTS", None)
    return subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=120, check=False).returncode


def _workspaces(t: Task) -> list[tuple[str, Workspace]]:
    out = []
    for c in battery(t).grounded:
        assert isinstance(c.payload, Workspace)
        out.append((c.provenance.operator, c.payload))
    return out


def test_a_grader_running_its_tests_apart_from_the_submission_is_never_accused(tmp_path: Path) -> None:
    """It passes the known-good solution, and rejects every tampered workspace."""
    assert (
        _pytest(
            Workspace({"{source_path}": REFERENCE}, parameters=("source_path",)), tmp_path / "reference", isolated=True
        )
        == 0
    )
    candidates = _workspaces(task(REFERENCE, shape=Shape.WORKSPACE))
    assert {operator for operator, _ in candidates} == {"future_repo_state", "parser_replaced", "test_framework_hook", "tests_deleted"}
    for operator, workspace in candidates:
        assert _pytest(workspace, tmp_path / operator, isolated=True) != 0, operator


def test_a_grader_trusting_pytest_in_the_submitted_tree_is_caught(tmp_path: Path) -> None:
    """It treats "no failures" (exit 0, or 5 for no tests ran) as a pass, in the tree the submission wrote."""
    for operator, workspace in _workspaces(task(REFERENCE, shape=Shape.WORKSPACE)):
        if operator in ("test_framework_hook", "tests_deleted"):
            assert _pytest(workspace, tmp_path / operator, isolated=False) in (0, 5), operator


def test_a_grader_that_only_checks_the_code_runs_is_still_caught() -> None:
    """The weak shape the README shows: it imports and calls the function, never checks the result."""

    def runs(payload: str) -> bool:
        namespace: dict[str, Any] = {}
        try:
            exec(compile(payload, "<fixture>", "exec"), namespace)
            namespace["solve"]([1, 2])
        except BaseException:
            return False
        return True

    hits = _accused(task(REFERENCE), runs)
    # It pays for the empty body, the constant and the object that equals everything, which all run;
    # the raising and the exiting ones do not.
    assert {hit.split(":", 1)[0] for hit in hits} == {
        "drop_side_effect",
        "constant_implementation",
        "equality_spoofing",
    }


def test_a_grader_accepting_anything_is_caught_by_every_grounded_candidate() -> None:
    result = battery(task(REFERENCE), [_OVERCLAIMS])
    assert len(_accused(task(REFERENCE), lambda _reply: True, [_OVERCLAIMS])) == len(result.grounded) > 0


def test_duplicate_payloads_are_tried_once() -> None:
    op = _Proposes(("0", Ground.DIFFERENTIAL), (" 0 ", Ground.DIFFERENTIAL), ("0\n", None))
    kept = [text(c).strip() for c in battery(task(REFERENCE), [op]).candidates]

    assert kept == ["0"]
