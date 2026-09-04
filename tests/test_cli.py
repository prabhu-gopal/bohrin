"""The CLI surface: exit codes, streams, and errors that are messages not tracebacks."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import pytest

from bohrin.cli import main
from bohrin.ir.task import Ground


def test_version_and_help_exit_zero(capsys: pytest.CaptureFixture[str]) -> None:
    for argv in (["--version"], ["--help"]):
        with pytest.raises(SystemExit) as exc:
            main(argv)
        assert exc.value.code == 0


def test_list_probes_names_both_open_probes(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list-probes"]) == 0
    out = capsys.readouterr().out
    assert "weak_oracle" in out
    assert "determinism" in out


def test_explain_prints_the_probe_rationale(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "weak_oracle"]) == 0
    assert "verifier" in capsys.readouterr().out.lower()


def test_explain_unknown_probe_lists_what_exists(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", "no_such_probe"]) == 1
    err = capsys.readouterr().err
    assert "unknown probe" in err.lower()
    assert "weak_oracle" in err, "telling the user what is wrong without what to try is not help"


def test_a_missing_path_is_a_message_not_a_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["audit", "./definitely-not-a-taskset"])
    captured = capsys.readouterr()

    assert code == 2
    assert captured.out == "", "a failed audit produces no findings on stdout"
    assert "error" in captured.err
    assert "Traceback" not in captured.err
    # The extras hint belongs on a path that exists in an unrecognised format — see
    # test_unknown_format_names_the_verifiers_extra. Offering it here would answer a
    # mistyped path with advice to install something, which is the wrong problem.
    assert "no such file or directory" in captured.err.lower()
    assert "pip install" not in captured.err


def test_unknown_format_names_the_verifiers_extra(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "some_file.txt").write_text("not a taskset", encoding="utf-8")

    assert main(["audit", str(tmp_path)]) == 2
    err = " ".join(capsys.readouterr().err.split())  # rich soft-wraps at the console width
    assert "bohrin[verifiers]" in err, "the extra must survive rendering — rich eats bare brackets"


# ------------------------------------------------------------- the repro command is real


def _report_with_one_exploit(target: str, isolation_none: bool) -> Any:
    """A report carrying one exploit, so the printed repro command can be inspected."""
    from bohrin.execute.isolation import Assessment, Isolation
    from bohrin.ir.evidence import Exploit
    from bohrin.ir.task import Candidate, Provenance, Verdict
    from bohrin.probes.base import ProbeResult, ProbeStatus
    from bohrin.report.model import Report
    from bohrin.scoring.gap import Coverage, GapScore

    exploit = Exploit(
        task_id="7",
        candidate=Candidate(
            payload="",
            provenance=Provenance(operator="empty_body", base="constant", detail="empty reply"),
            ground=Ground.STRUCTURAL,
        ),
        verdict=Verdict(reward=1.0, passed=True),
        repro_args="--task 7 --operator empty_body",
    )
    return Report(
        target=target,
        adapter="verifiers_v1",
        gap=GapScore(score=50.0, coverage=Coverage(measured=("weak_oracle",), total=1)),
        results=(
            ProbeResult(
                probe_id="weak_oracle",
                status=ProbeStatus.OK,
                sub_score=1.0,
                tasks_probed=1,
                findings=(exploit,),
            ),
        ),
        tasks_total=1,
        isolation=Assessment(
            effective=Isolation.NONE if isolation_none else Isolation.CONTAINER,
            best_available=Isolation.NONE if isolation_none else Isolation.CONTAINER,
            already_contained=not isolation_none,
        ),
    )


def test_the_printed_repro_command_is_accepted_by_the_parser() -> None:
    """A finding is evidence only if the reader can re-run it.

    Every finding prints a command. Before this was checked, that command named `--task`
    and `--operator`, which the parser did not define — so the first thing a customer
    would do with a finding was run a command that errors.
    """
    from bohrin.cli import _parser

    command = _report_with_one_exploit("./environments/my-taskset", isolation_none=True)
    printed = command.command_for(command.results[0].findings[0])

    assert printed.startswith("bohrin audit ")
    args = _parser().parse_args(shlex.split(printed)[1:])  # drop the program name

    assert args.path == "./environments/my-taskset", "the repro must name the taskset it came from"
    assert args.task == ["7"]
    assert args.operator == ["empty_body"]
    assert args.unsafe_local is True, "an audit that ran with no boundary cannot be re-run without the flag"


def test_the_repro_command_omits_unsafe_local_when_it_was_not_needed() -> None:
    """Printing it unconditionally would teach the reader to pass it by reflex."""
    report = _report_with_one_exploit("./envs/t", isolation_none=False)

    assert "--unsafe-local" not in report.command_for(report.results[0].findings[0])


def test_a_target_with_spaces_survives_the_repro_command() -> None:
    report = _report_with_one_exploit("./my envs/task set", isolation_none=False)
    printed = report.command_for(report.results[0].findings[0])

    from bohrin.cli import _parser

    args = _parser().parse_args(shlex.split(printed)[1:])
    assert args.path == "./my envs/task set", "an unquoted path would split into two arguments"


def test_a_single_task_is_not_reported_as_1_tasks() -> None:
    """Grammar is not cosmetic in a report whose product is rigour."""
    import io

    from rich.console import Console

    from bohrin.report.tty import render

    buf = io.StringIO()
    render(_report_with_one_exploit("./envs/t", isolation_none=True), Console(file=buf, width=200, no_color=True))
    out = buf.getvalue()

    assert "1 task ·" in out and "1 tasks" not in out
    assert "1 probe ·" in out and "1 probes" not in out
    assert "1 task accepts a known-wrong solution" in out, "the verb must agree with the count"
