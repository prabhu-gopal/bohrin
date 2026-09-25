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
from bohrin.history import git, oracle
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
        # Compound and indirect forms: `and` checks both parts, `or` only its weakest, `not` its operand.
        ("assert f(1) == 1 and f(2) == 2", "S1"),
        ("assert f(1) == 1 and 1 in f()", "S3"),
        ("assert f(1) == 1 or f(1) is None", "W2"),
        ("assert not (f(1) is None)", "W2"),
        ("assert not f(1) == 2", "S1"),
        ("assert f(1) != None", "W2"),
        ("assert None is not f(1)", "W2"),
        ("assert m.call_count == 1", "W4"),
        ("assert m.called", "W4"),
        ("self.assertTrue(f(1) == 1)", "S1"),
        ("self.assertTrue(f(1))", "W3"),
        ("self.assertFalse(f(1) is None)", "W2"),
        ("assert 0 < f(1) < 5", "S1"),
        ("assert isinstance(f(1), int)", "S2"),
        ("snapshot.assert_match(f(1))", "W5"),
        ("self.assertMatchSnapshot(f(1))", "W5"),
        ("self.assertIsNone(f(1))", "W2"),
    ],
)
def test_checks_are_classified_as_the_published_taxonomy_defines(body: str, category: str) -> None:
    node = ast.parse(_test(body)).body[1]
    assert isinstance(node, ast.FunctionDef)
    assert oracle.strength(node) == category


def _one(body: str, name: str = "test_it") -> ast.FunctionDef:
    node = ast.parse(_test(body, name)).body[1]
    assert isinstance(node, ast.FunctionDef)
    return node


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("assert f(1) == 1", "assert f(1) == 1 and f(2) == 2"),
        ("assert f(1) == 1", "self.assertTrue(f(1) == 1)"),
        ("assert f(1) == 1", "assert not f(1) != 1"),
    ],
    ids=["a second condition", "the same check through assertTrue", "a negated inequality"],
)
def test_a_stricter_or_equal_check_is_never_called_weakened(before: str, after: str) -> None:
    assert "check-weakened" not in _rules({T: _test(before)}, {T: _test(after)})


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("assert f(1) == 1", "assert f(1) != None"),
        ("assert f(1) == 1", "assert f(1) == 1 or f(1) is None"),
        ("assert f(1) == [1]", "assert m.call_count == 1"),
    ],
    ids=["a value check became != None", "an escape hatch added with or", "a value check became a call count"],
)
def test_a_weaker_check_in_disguise_is_still_called_weakened(before: str, after: str) -> None:
    assert "check-weakened" in _rules({T: _test(before)}, {T: _test(after)})


@pytest.mark.parametrize(
    ("before", "after", "key"),
    [
        ("assert f() == pytest.approx(1)", "assert f() == pytest.approx(1, 0.5)", "approx.rel"),
        ("assert np.allclose(f(), 1)", "assert np.allclose(f(), 1, 0.5)", "allclose.rtol"),
        ("np.testing.assert_allclose(f(), 1)", "np.testing.assert_allclose(f(), 1, 0.5)", "assert_allclose.rtol"),
        ("assert np.isclose(f(), 1)", "assert np.isclose(f(), 1, rtol=0.5)", "numpy.isclose.rtol"),
        ("assert math.isclose(f(), 1)", "assert math.isclose(f(), 1, rel_tol=0.5)", "isclose.rel_tol"),
    ],
)
def test_a_tolerance_loosened_positionally_or_through_numpy_is_seen(before: str, after: str, key: str) -> None:
    loosened = [f for f in facts({T: _test(before)}, {T: _test(after)})[0] if f.rule == "tolerance-loosened"]
    assert loosened and key in loosened[0].message


def test_numpy_and_standard_library_isclose_are_not_confused() -> None:
    """NumPy's isclose names its tolerances rtol and atol; they are not math.isclose's rel_tol."""
    assert set(oracle.tolerances(_one("assert np.isclose(f(), 1)"))) == {"numpy.isclose.rtol", "numpy.isclose.atol"}
    assert set(oracle.tolerances(_one("assert math.isclose(f(), 1)"))) == {"isclose.rel_tol", "isclose.abs_tol"}


def test_an_expected_value_on_the_left_is_still_an_expected_value() -> None:
    changed = _rules({T: _test("assert 5 == f(1)")}, {T: _test("assert 6 == f(1)")})
    assert "expected-value-changed" in changed
    assert oracle.expected_values(_one("assertEqual(5, f(1))")) == oracle.expected_values(_one("assert f(1) == 5"))
    assert oracle.expected_values(_one("assert 1 == 1")) == {}, "two constants check nothing about the code"


@pytest.mark.parametrize(
    "after",
    [
        "with contextlib.suppress(AssertionError):\n    assert f(1) == 1",
        "with suppress(Exception):\n    assert f(1) == 1",
        "try:\n    assert f(1) == 1\nexcept* AssertionError:\n    pass",
    ],
)
def test_a_check_silenced_by_suppress_or_except_star_is_seen(after: str) -> None:
    assert "failure-swallowed" in _rules({T: _test("assert f(1) == 1")}, {T: _test(after)})


def test_suppressing_an_unrelated_error_silences_nothing() -> None:
    after = "with contextlib.suppress(FileNotFoundError):\n    os.remove('x')\nassert f(1) == 1"
    assert "failure-swallowed" not in _rules({T: _test("assert f(1) == 1")}, {T: _test(after)})


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


# --------------------------------------------------------------------------- moves, configs and limits

_CLASS = (
    "import unittest\n\nclass TestA(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(f(1), 2)\n"
)


@pytest.mark.parametrize(
    "after",
    [
        _CLASS.replace("TestA", "TestParse"),
        "def test_x():\n    assert f(1) == 2\n",
        "import unittest\n\nclass TestA(unittest.TestCase):\n    pass\n\n"
        + _CLASS.split("\n\n", 1)[1].replace("TestA", "TestB"),
    ],
    ids=["class renamed", "method made a function", "method moved to another class"],
)
def test_a_test_moved_between_classes_is_not_removed(after: str) -> None:
    rules = _rules({T: _CLASS}, {T: after})
    assert "tests-removed" not in rules and "check-weakened" not in rules


def test_a_test_weakened_while_its_class_was_renamed_is_still_seen() -> None:
    after = _CLASS.replace("TestA", "TestParse").replace("self.assertEqual(f(1), 2)", "self.assertIsNotNone(f(1))")
    assert "check-weakened" in _rules({T: _CLASS}, {T: after})


def test_a_test_method_really_removed_is_still_removed() -> None:
    after = "import unittest\n\nclass TestA(unittest.TestCase):\n    pass\n"
    assert "tests-removed" in _rules({T: _CLASS}, {T: after})


def test_a_moved_test_without_assertions_is_not_reported_as_new() -> None:
    before = "def test_smoke():\n    f(1)\n"
    after = "class TestSmoke:\n    def test_smoke(self):\n        f(1)\n"
    assert "tests-without-checks" not in _rules({T: before}, {T: after})


@pytest.mark.parametrize(
    ("path", "before", "after"),
    [
        ("pytest.ini", "[pytest]\naddopts = -q\n", "[pytest\naddopts = -k nothing\n"),
        (
            "pyproject.toml",
            '[tool.pytest.ini_options]\naddopts = "-q"\n',
            '[tool.pytest.ini_options\naddopts = "-k nothing"\n',
        ),
    ],
)
def test_a_configuration_that_no_longer_parses_is_not_checked_rather_than_changed(
    path: str, before: str, after: str
) -> None:
    found, unreadable = facts({path: before}, {path: after})
    assert "selection-changed" not in [f.rule for f in found]
    assert unreadable == [path]


@pytest.mark.parametrize(
    ("rule", "before", "after"),
    [
        ("trivial-checks-added", {T: _test("assert f(1) == 1")}, {T: _test("assert f(1) == 1\nself.assertTrue(True)")}),
        ("exit-added", {"src/a.py": "def f():\n    return 1\n"}, {"src/a.py": "def f():\n    raise SystemExit(0)\n"}),
        (
            "timer-reassigned",
            {"src/a.py": "import time\n"},
            {"src/a.py": "import time\nsetattr(time, 'perf_counter', lambda: 0.0)\n"},
        ),
        ("replaced-by-stub", {"src/a.py": "def f(x):\n    return x + 1\n"}, {"src/a.py": "def f(x):\n    pass\n"}),
    ],
    ids=["assertTrue(True)", "raise SystemExit", "setattr on a timer", "a body of pass"],
)
def test_each_indirect_form_of_a_rule_is_seen(
    rule: str, before: dict[str, str | None], after: dict[str, str | None]
) -> None:
    assert rule in _rules(before, after)


def test_a_test_file_that_never_had_tests_loses_none() -> None:
    assert "tests-removed" not in _rules({T: "import pytest\n"}, {T: None})


def test_a_huge_committed_file_is_refused_before_it_is_read(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Its size is read from the tree listing, so a huge blob in history is never loaded into memory."""
    import bohrin.history.verify as verify_module

    (repo / "tests" / "test_big.py").write_text("x = 1\n" * 50)
    _run_git(repo, "add", "-A")
    _commit(repo, "Add a big file")
    (repo / "tests" / "test_big.py").write_text("x = 2\n")
    monkeypatch.setattr(verify_module, "MAX_BYTES", 100)
    reads: list[str] = []
    original = git.read_at

    def recording(root: Path, commit: str, path: str) -> bytes:
        reads.append(path)
        return original(root, commit, path)

    monkeypatch.setattr(git, "read_at", recording)
    report = verify(repo, "HEAD")

    assert "tests/test_big.py" not in reads
    assert any("tests/test_big.py" in item for item in report.not_checked)


def test_the_tree_listing_gives_sizes_and_leaves_out_submodules(repo: Path) -> None:
    sizes = git.files_at(repo, git.resolve(repo, "HEAD"))
    assert sizes["src.py"] == len((repo / "src.py").read_bytes())
    _run_git(repo, "update-index", "--add", "--cacheinfo", f"160000,{'a' * 40},vendor/lib")
    _run_git(repo, "commit", "-q", "-m", "Add a submodule")
    assert "vendor/lib" not in git.files_at(repo, git.resolve(repo, "HEAD"))


def test_a_file_reached_through_a_symlinked_directory_is_not_read(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test_secret.py").write_text("def test_s():\n    assert 1 == 1\n")
    (repo / "linked").symlink_to(outside, target_is_directory=True)
    report = verify(repo, "HEAD")
    assert all("test_secret" not in f.path for f in report.facts)
    # git never lists a file behind a symlinked directory; the reader refuses one on its own too.
    import bohrin.history.verify as verify_module

    with pytest.raises(ValueError, match="outside the repository"):
        verify_module._read_disk(repo, repo / "linked" / "test_secret.py")


# --------------------------------------------------------------------------- where the comparison starts


def test_with_no_remote_the_comparison_starts_at_the_previous_commit(repo: Path) -> None:
    first = git.resolve(repo, "HEAD")
    (repo / "src.py").write_text("def f(x):\n    return x + 2\n")
    _commit(repo, "Change f")
    assert git.default_base(repo) == first


def test_a_repository_with_one_commit_compares_with_it(repo: Path) -> None:
    assert git.default_base(repo) == git.resolve(repo, "HEAD")


def test_a_branch_is_compared_with_where_it_left_the_remote_default(repo: Path, tmp_path: Path) -> None:
    started = git.resolve(repo, "HEAD")
    _run_git(repo, "update-ref", "refs/remotes/origin/main", started)
    _run_git(repo, "checkout", "-q", "-b", "feature")
    for n in (1, 2):
        (repo / "src.py").write_text(f"def f(x):\n    return x + {n + 1}\n")
        _commit(repo, f"Step {n}")
    assert git.default_base(repo) == started, "both commits on the branch are compared, not only the last"


def test_an_empty_repository_cannot_be_compared(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    _run_git(empty, "init", "-q")
    with pytest.raises(git.GitError, match="no commits"):
        git.default_base(empty)


def test_git_missing_or_hanging_is_a_clear_error(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("git")

    def hangs(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("git", git.TIMEOUT_S)

    monkeypatch.setattr(subprocess, "run", missing)
    with pytest.raises(git.GitError, match="not installed"):
        git.top_level(repo)
    monkeypatch.setattr(subprocess, "run", hangs)
    with pytest.raises(git.GitError, match="did not answer"):
        git.top_level(repo)


def test_a_sarif_file_that_cannot_be_written_cannot_run(repo: Path, tmp_path: Path) -> None:
    target = tmp_path / "missing-directory" / "out.sarif"
    assert main(["verify", "--since", "HEAD", "--sarif", str(target), str(repo)]) == CANNOT_RUN


def test_fewer_decimal_places_is_a_looser_tolerance() -> None:
    before, after = "self.assertAlmostEqual(f(), 1.0, places=7)", "self.assertAlmostEqual(f(), 1.0, 2)"
    loosened = [f for f in facts({T: _test(before)}, {T: _test(after)})[0] if f.rule == "tolerance-loosened"]
    assert loosened and "assertAlmostEqual.places" in loosened[0].message


def test_a_bare_except_swallows_a_check() -> None:
    after = "try:\n    assert f(1) == 1\nexcept:\n    pass"
    assert "failure-swallowed" in _rules({T: _test("assert f(1) == 1")}, {T: _test(after)})


@pytest.mark.parametrize(
    "patch",
    [
        "mock.patch.object(pkg, 'parse')",
        "monkeypatch.setattr(pkg, 'parse', lambda x: 1)",
        "monkeypatch.setattr('pkg.parse', lambda x: 1)",
    ],
)
def test_each_way_of_patching_the_subject_is_seen(patch: str) -> None:
    assert oracle.mocked_subjects(_one(patch, "test_parse")) == {"parse"}


def test_a_patch_target_without_a_word_is_not_the_subject() -> None:
    assert oracle.mocked_subjects(_one("monkeypatch.setattr(pkg, '_', 1)", "test_parse")) == set()
