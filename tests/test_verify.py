"""``bohrin verify``: every rule catches its pattern and stays quiet on the honest version of it.

Three groups. The fact rules, on before-and-after file contents, each tested in both directions,
because a rule that fires on honest refactors trains people to ignore it. The git layer, in real
temporary repositories, including one booby-trapped the way hostile repositories are, to show that
reading history runs nothing the repository names. And the command, against its exit-code contract.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from bohrin.cli import CANNOT_RUN, CLEAN, FINDINGS, main
from bohrin.history import oracle
from bohrin.history.facts import facts, is_test_file, success_claims
from bohrin.history.git import GitError, resolve
from bohrin.history.verify import render, verify, verify_report_schema

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _rules(before: dict[str, str | None], after: dict[str, str | None]) -> list[str]:
    return [fact.rule for fact in facts(before, after)[0]]


def _test(body: str, name: str = "test_it") -> str:
    return f"import pytest\n\ndef {name}():\n" + "".join(f"    {line}\n" for line in body.splitlines())


T = "tests/test_parse.py"

# --------------------------------------------------------------------------- the rules, both ways


@pytest.mark.parametrize(
    ("rule", "before", "after"),
    [
        ("tests-removed", {T: _test("assert f(1) == 1")}, {T: None}),
        ("check-weakened", {T: _test("assert f(1) == 1")}, {T: _test("assert f(1) is not None")}),
        ("check-weakened", {T: _test("with pytest.raises(ValueError):\n    f('x')")}, {T: _test("f('x')")}),
        ("checks-removed", {T: _test("assert f(1) == 1\nassert f(2) == 2")}, {T: _test("assert f(1) == 1")}),
        (
            "skips-added",
            {T: _test("assert f(1) == 1")},
            {T: "import pytest\n@pytest.mark.skip\n" + _test("assert f(1) == 1")[14:]},
        ),
        (
            "tolerance-loosened",
            {T: _test("assert f() == pytest.approx(1)")},
            {T: _test("assert f() == pytest.approx(1, rel=0.5)")},
        ),
        (
            "timeout-raised",
            {T: "import pytest\n@pytest.mark.timeout(1)\n" + _test("assert f() == 1")[14:]},
            {T: "import pytest\n@pytest.mark.timeout(60)\n" + _test("assert f() == 1")[14:]},
        ),
        (
            "failure-swallowed",
            {T: _test("assert f(1) == 1")},
            {T: _test("try:\n    assert f(1) == 1\nexcept AssertionError:\n    pass")},
        ),
        ("expected-value-changed", {T: _test("assert f(2) == 4")}, {T: _test("assert f(2) == 5")}),
        (
            "subject-mocked",
            {T: _test("assert parse('1') == 1", "test_parse")},
            {T: _test("with patch('pkg.parse'):\n    assert parse('1') == 1", "test_parse")},
        ),
        ("trivial-checks-added", {T: _test("assert f(1) == 1")}, {T: _test("assert f(1) == 1\nassert True")}),
        (
            "report-hook-added",
            {"tests/conftest.py": "import pytest\n"},
            {"tests/conftest.py": "def pytest_runtest_makereport(item, call):\n    pass\n"},
        ),
        (
            "selection-changed",
            {"pytest.ini": "[pytest]\naddopts = -q\n"},
            {"pytest.ini": "[pytest]\naddopts = -q -k 'not slow'\n"},
        ),
        (
            "selection-changed",
            {"pyproject.toml": "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"},
            {"pyproject.toml": "[tool.pytest.ini_options]\ntestpaths = ['tests/unit']\n"},
        ),
        (
            "replaced-by-stub",
            {"src/a.py": "def f(x):\n    return x + 1\n"},
            {"src/a.py": "def f(x):\n    raise NotImplementedError\n"},
        ),
        (
            "exit-added",
            {"src/a.py": "def f():\n    return 1\n"},
            {"src/a.py": "import sys\ndef f():\n    sys.exit(0)\n"},
        ),
        (
            "always-equal-added",
            {"src/a.py": "class A:\n    pass\n"},
            {"src/a.py": "class A:\n    def __eq__(self, other):\n        return True\n"},
        ),
        (
            "timer-reassigned",
            {"src/bench.py": "import time\n"},
            {"src/bench.py": "import time\ntime.perf_counter = lambda: 0.0\n"},
        ),
    ],
)
def test_each_rule_catches_its_pattern(rule: str, before: dict[str, str | None], after: dict[str, str | None]) -> None:
    assert rule in _rules(before, after)


@pytest.mark.parametrize(
    ("honest", "before", "after"),
    [
        (
            "a test moved to another file",
            {T: _test("assert f(1) == 1"), "tests/test_b.py": None},
            {T: None, "tests/test_b.py": _test("assert f(1) == 1")},
        ),
        ("an assertion reformatted", {T: _test("assert f(1) == 1")}, {T: _test("assert f(1)    ==   1  # same")}),
        ("a new test with a real check", {T: None}, {T: _test("assert f(1) == 1")}),
        ("a determinism check that calls twice", {T: _test("x = 1")}, {T: _test("assert f(1) == f(1)")}),
        (
            "a tolerance tightened",
            {T: _test("assert f() == pytest.approx(1, rel=0.1)")},
            {T: _test("assert f() == pytest.approx(1, rel=0.01)")},
        ),
        (
            "a dependency patched",
            {T: _test("assert parse('1') == 1", "test_parse")},
            {T: _test("with patch('requests.get'):\n    assert parse('1') == 1", "test_parse")},
        ),
        (
            "a stub that was always a stub",
            {"src/a.py": "def f():\n    raise NotImplementedError\n"},
            {"src/a.py": "def f():\n    '''Doc.'''\n    raise NotImplementedError\n"},
        ),
        ("a test made stronger", {T: _test("assert f(1) is not None")}, {T: _test("assert f(1) == 1")}),
        (
            "an unrelated config change",
            {"pytest.ini": "[pytest]\naddopts = -q\n"},
            {"pytest.ini": "[pytest]\naddopts = -q\nfilterwarnings = error\n"},
        ),
    ],
)
def test_no_rule_fires_on_honest_changes(
    honest: str, before: dict[str, str | None], after: dict[str, str | None]
) -> None:
    kinds = {fact.kind for fact in facts(before, after)[0]}
    assert "fact" not in kinds, honest


def test_a_conditional_skip_is_an_observation_not_a_fact() -> None:
    guarded = _test("if not has_gpu():\n    pytest.skip('no gpu')\nassert f() == 1")
    found = facts({T: _test("assert f() == 1")}, {T: guarded})[0]
    assert [(f.rule, f.kind) for f in found] == [("conditional-skips-added", "observation")]


def test_a_file_that_does_not_parse_is_listed_not_guessed() -> None:
    found, unreadable = facts({T: _test("assert f() == 1")}, {T: "def broken(:\n"})
    assert found == [] and unreadable == [T]


@pytest.mark.parametrize(
    ("path", "is_test"),
    [
        ("tests/test_a.py", True),
        ("test_a.py", True),
        ("pkg/a_test.py", True),
        ("tests/conftest.py", True),
        ("src/pkg/a.py", False),
        ("src/testing_utils.py", False),
        ("tests/data.json", False),
    ],
)
def test_test_files_are_recognised_as_pytest_does(path: str, is_test: bool) -> None:
    assert is_test_file(path) is is_test


# --------------------------------------------------------------------------- oracle strength


@pytest.mark.parametrize(
    ("body", "category"),
    [
        ("assert f(1) == 1", "S1"),
        ("with pytest.raises(ValueError):\n    f('x')", "S2"),
        ("assert 1 in f()", "S2"),
        ("assert f(1) == 1\nwith pytest.raises(ValueError):\n    f('x')", "S3"),
        ("f(1)", "W1"),
        ("assert f(1) is not None", "W2"),
        ("assert f(1)", "W3"),
        ("m.assert_called_once()", "W4"),
        ("assert f() == snapshot", "W5"),
    ],
)
def test_checks_are_classified_as_the_published_taxonomy_defines(body: str, category: str) -> None:
    node = ast.parse(_test(body)).body[1]
    assert isinstance(node, ast.FunctionDef)
    assert oracle.strength(node) == category


# --------------------------------------------------------------------------- claims of success


@pytest.mark.parametrize(
    ("message", "claims"),
    [
        ("Fix the parser", True),
        ("Resolves #12: handle empty input", True),
        ("Refactor the reader\n\nAll tests pass now.", True),
        ("Document the tutorial\n\nlinks resolve and examples run", False),
        ("Add a prefix option", False),
        ("Explain what was done in the README", False),
    ],
)
def test_success_is_claimed_by_a_subject_verb_or_an_explicit_phrase(message: str, claims: bool) -> None:
    assert bool(success_claims([("abc1234", message)])) is claims


# --------------------------------------------------------------------------- real repositories


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _run_git(root, "init", "-q", "-b", "main")
    _run_git(root, "config", "user.email", "test@example.com")
    _run_git(root, "config", "user.name", "Test")
    _run_git(root, "config", "commit.gpgsign", "false")
    (root / "tests").mkdir()
    (root / "src.py").write_text("def f(x):\n    return x + 1\n")
    (root / "tests" / "test_src.py").write_text(_test("assert f(1) == 2\nassert f(2) == 3", "test_f"))
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "-q", "-m", "Start")
    return root


def _commit(root: Path, message: str) -> None:
    _run_git(root, "add", "-A")
    _run_git(root, "commit", "-q", "-m", message)


def test_a_clean_change_has_nothing_to_report(repo: Path) -> None:
    (repo / "src.py").write_text("def f(x):\n    return 1 + x\n")
    _commit(repo, "Tidy f")
    report = verify(repo, "HEAD~1")
    assert report.facts == () and "Nothing in this change" in render(report)


def test_committed_and_uncommitted_weakening_are_both_seen(repo: Path) -> None:
    (repo / "tests" / "test_src.py").write_text(_test("assert f(1) == 2", "test_f"))
    _commit(repo, "Fix f")
    (repo / "src.py").write_text("def f(x):\n    raise NotImplementedError\n")  # uncommitted
    report = verify(repo, "HEAD~1")

    assert {f.rule for f in report.facts} >= {"checks-removed", "replaced-by-stub"}
    assert report.claims == (report.claims[0],) and report.claims[0][1] == "Fix f"


def test_a_new_untracked_test_file_is_read(repo: Path) -> None:
    (repo / "tests" / "test_new.py").write_text(_test("f(1)", "test_runs"))
    assert "tests-without-checks" in {f.rule for f in verify(repo, "HEAD").facts}


def test_a_symlink_is_not_followed(repo: Path) -> None:
    """A hostile repository could point a test file at a device that never stops reading."""
    target = "/dev/zero" if os.path.exists("/dev/zero") else str(repo / "src.py")
    (repo / "tests" / "test_link.py").symlink_to(target)
    report = verify(repo, "HEAD")
    assert "tests/test_link.py" not in report.changed


def test_reading_history_runs_nothing_the_repository_names(repo: Path, tmp_path: Path) -> None:
    """The repository asks git to run programs on status, diff and filtering; none of them runs."""
    marker = tmp_path / "ran"
    trap = tmp_path / "trap.sh"
    trap.write_text(f"#!/bin/sh\necho ran >> {marker}\ncat\n")
    trap.chmod(0o755)
    _run_git(repo, "config", "core.fsmonitor", str(trap))
    _run_git(repo, "config", "diff.external", str(trap))
    _run_git(repo, "config", "filter.trap.clean", str(trap))
    _run_git(repo, "config", "filter.trap.smudge", str(trap))
    _run_git(repo, "config", "diff.trap.textconv", str(trap))
    (repo / ".gitattributes").write_text("*.py filter=trap diff=trap\n")
    (repo / "tests" / "test_src.py").write_text(_test("assert f(1) is not None", "test_f"))

    report = verify(repo, "HEAD")
    assert "check-weakened" in {f.rule for f in report.facts}, "the check still worked"
    assert not marker.exists(), "a program named by the repository ran"

    # The counterweight: the trap is live. Plain git runs it, so a pass above is not a dead trap.
    subprocess.run(["git", "-C", str(repo), "diff"], capture_output=True, check=False)
    assert marker.exists(), "the trap should fire under an ordinary git diff"


def test_an_unknown_ref_is_a_clear_error(repo: Path) -> None:
    with pytest.raises(GitError, match="names no commit"):
        resolve(repo, "no-such-branch")


# --------------------------------------------------------------------------- the command


def test_the_exit_codes_follow_the_contract(repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["verify", "--since", "HEAD", str(repo)]) == CLEAN

    (repo / "tests" / "test_src.py").write_text(_test("assert f(1) == 2", "test_f"))
    _commit(repo, "Refactor tests")
    assert main(["verify", "--since", "HEAD~1", str(repo)]) == CLEAN, "facts alone are not a failure"
    assert main(["verify", "--since", "HEAD~1", "--strict", str(repo)]) == FINDINGS

    (repo / "tests" / "test_src.py").write_text(_test("assert f(1) is not None", "test_f"))
    _commit(repo, "Fix the edge case, all tests pass")
    assert main(["verify", "--since", "HEAD~1", str(repo)]) == FINDINGS, "facts beside a claim of success"

    assert main(["verify", "--since", "nope", str(repo)]) == CANNOT_RUN
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    assert main(["verify", str(outside)]) == CANNOT_RUN
    assert "cannot read the history" in capsys.readouterr().err


def test_json_output_conforms_to_its_schema(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "tests" / "test_src.py").write_text(_test("assert f(1) is not None", "test_f"))
    main(["verify", "--since", "HEAD", "--json", str(repo)])
    report = json.loads(capsys.readouterr().out)

    assert list(Draft202012Validator(verify_report_schema()).iter_errors(report)) == []
    assert report["facts"][0]["rule"] == "check-weakened"
