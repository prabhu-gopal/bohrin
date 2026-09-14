"""Values that cannot produce a measurement are refused as bad input, not run.

Each of these used to be accepted. The audit then measured nothing and exited 0, which in CI
reads as a clean build: ``--max-tasks 0`` audited no tasks, ``--timeout 0`` abandoned every
scoring call, ``--fail-on-gap 150`` set a gate the gap can never reach, and ``--sample-seed``
without ``--max-tasks`` was ignored outright — a run asking for a sample audited the whole
taskset and recorded no seed. Refusal happens at parse time, before any taskset code runs, so
none of these tests need a real taskset.
"""

from __future__ import annotations

import pytest

from bohrin.cli import EXIT_USER_ERROR, main

# The path is never read: every case here must be refused before the audit looks at it.
_PATH = "./never-read"


def _refused(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    with pytest.raises(SystemExit) as exc:
        main(["audit", _PATH, *argv])
    assert exc.value.code == EXIT_USER_ERROR, f"{argv} must exit {EXIT_USER_ERROR} (bad input)"
    captured = capsys.readouterr()
    assert captured.out == "", "a refused run produces nothing on stdout"
    assert "Traceback" not in captured.err
    return " ".join(captured.err.split())


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (["--max-tasks", "0"], "at least 1"),
        (["--max-tasks", "-5"], "at least 1"),
        (["--max-tasks", "five"], "expected an integer"),
        (["--repeats", "0"], "at least 2"),
        (["--repeats", "1"], "at least 2"),
        (["--concurrency", "-1"], "at least 0"),
        (["--timeout", "0"], "greater than 0"),
        (["--timeout", "-3"], "greater than 0"),
        (["--timeout", "nan"], "greater than 0"),
        (["--fail-on-gap", "150"], "between 0 and 100"),
        (["--fail-on-gap", "-1"], "between 0 and 100"),
        (["--fail-on-gap", "nan"], "between 0 and 100"),
    ],
)
def test_a_value_that_measures_nothing_is_refused(
    argv: list[str], says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    err = _refused(argv, capsys)
    assert argv[0] in err, "the message names the flag that was wrong"
    assert says in err


def test_a_sample_seed_without_a_bound_is_refused_not_ignored(capsys: pytest.CaptureFixture[str]) -> None:
    err = _refused(["--sample-seed", "7"], capsys)
    assert "--sample-seed" in err
    assert "--max-tasks" in err, "the fix is to add a bound, so the message says so"


@pytest.mark.parametrize(
    "argv",
    [
        ["--max-tasks", "1"],
        ["--max-tasks", "100", "--sample-seed", "7"],
        ["--max-tasks", "10", "--sample-seed", "-1"],
        ["--repeats", "2"],
        ["--concurrency", "0"],
        ["--timeout", "0.5"],
        ["--fail-on-gap", "0"],
        ["--fail-on-gap", "100"],
    ],
)
def test_the_boundary_values_themselves_are_accepted(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    # Accepted means parsing passed and the audit went on to look for the taskset, which is
    # missing — so the failure is the ordinary missing-path message, not an argument error.
    assert main(["audit", _PATH, *argv]) == EXIT_USER_ERROR
    err = " ".join(capsys.readouterr().err.split()).lower()
    assert "no such file or directory" in err
    assert "must be" not in err
