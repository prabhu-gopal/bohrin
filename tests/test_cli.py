"""The CLI surface: exit codes, streams, and errors that are messages not tracebacks."""

from __future__ import annotations

import shlex
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from bohrin.cli import EXIT_CLEAN, EXIT_FINDINGS, EXIT_UNDECIDED, EXIT_USER_ERROR, main
from bohrin.ir.task import Ground
from bohrin.probes.base import ProbeStatus


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
    assert main(["explain", "no_such_probe"]) == EXIT_USER_ERROR
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


# ----------------------------------------------------------------------- the CI gate


def _gate_on(report: Any, **flags: Any) -> int:
    """Run the gate alone, so the contract is tested without a live taskset."""
    import argparse
    import io

    from rich.console import Console

    from bohrin.cli import _gate

    args = argparse.Namespace(**{"fail_on_finding": False, "fail_on_gap": None, **flags})
    return _gate(args, report, Console(file=io.StringIO(), no_color=True))


def test_without_a_gate_flag_an_audit_with_findings_still_exits_zero() -> None:
    """Gating is opt-in, as in `semgrep scan` and `trivy`.

    Anyone already scripting `bohrin audit` must not start failing because a gate was
    added, so the default has to stay 0 even when the audit reports exploits.
    """
    assert _gate_on(_report_with_one_exploit("./t", isolation_none=True)) == EXIT_CLEAN


def test_a_finding_fails_the_gate_when_asked() -> None:
    report = _report_with_one_exploit("./t", isolation_none=True)
    assert _gate_on(report, fail_on_finding=True) == EXIT_FINDINGS


def test_the_gap_threshold_is_inclusive() -> None:
    report = _report_with_one_exploit("./t", isolation_none=True)  # gap 50
    assert _gate_on(report, fail_on_gap=50.0) == EXIT_FINDINGS
    assert _gate_on(report, fail_on_gap=51.0) == EXIT_CLEAN


def test_an_unmeasured_audit_is_undecided_and_never_passes_a_gate() -> None:
    """The failure this exit code exists for.

    A gap of None means no probe produced a measurement. Comparing that numerically
    would read as clean and merge the pipeline — the same trap trivy documents, where a
    missing flag lets critical findings through. "We could not tell" is not "it is fine",
    so it gets its own code rather than being folded into either.
    """
    from bohrin.scoring.gap import Coverage, GapScore

    report = _report_with_one_exploit("./t", isolation_none=True)
    blind = replace(report, gap=GapScore(score=None, coverage=Coverage((), 2)))

    assert _gate_on(blind, fail_on_gap=90.0) == EXIT_UNDECIDED
    assert _gate_on(blind, fail_on_finding=True) == EXIT_UNDECIDED


def test_a_probe_that_failed_leaves_the_gate_undecided() -> None:
    """A gap computed from one of two probes is a different quantity, not a lenient one."""
    from bohrin.probes.base import ProbeResult
    from bohrin.scoring.gap import Coverage, GapScore

    report = _report_with_one_exploit("./t", isolation_none=True)
    partial = replace(
        report,
        gap=GapScore(score=0.0, coverage=Coverage(("weak_oracle",), 2)),
        results=(
            report.results[0],
            ProbeResult(probe_id="determinism", status=ProbeStatus.ERROR, reason="every call failed"),
        ),
    )

    assert _gate_on(partial, fail_on_gap=10.0) == EXIT_UNDECIDED


def test_a_probe_that_did_not_apply_does_not_block_the_gate() -> None:
    """The distinction the gate turns on, and a regression that actually happened.

    A probe that *failed* leaves the verdict undecided. A probe that does not **apply** —
    `ground_truth_rejected` against a taskset with no declared answer — has nothing to
    measure rather than an unmeasured gap. Conflating them made four clean public
    environments start failing CI the moment a third probe was registered, which is a
    worse failure than the one the exit code exists to prevent.
    """
    from bohrin.probes.base import ProbeResult
    from bohrin.scoring.gap import Coverage, GapScore

    report = _report_with_one_exploit("./t", isolation_none=True)
    clean = replace(
        report,
        gap=GapScore(score=0.0, coverage=Coverage(("weak_oracle",), 2)),
        results=(
            replace(report.results[0], sub_score=0.0, findings=()),
            ProbeResult(
                probe_id="ground_truth_rejected",
                status=ProbeStatus.NOT_APPLICABLE,
                reason="no task has a declared answer",
            ),
        ),
    )

    assert _gate_on(clean, fail_on_gap=10.0) == EXIT_CLEAN
    assert _gate_on(clean, fail_on_finding=True) == EXIT_CLEAN


def test_a_clean_fully_covered_audit_passes_the_gate() -> None:
    """The counterweight: the gate must be passable, or it is just a failure generator."""
    from bohrin.probes.base import ProbeResult, ProbeStatus
    from bohrin.scoring.gap import Coverage, GapScore

    report = _report_with_one_exploit("./t", isolation_none=True)
    clean = replace(
        report,
        gap=GapScore(score=0.0, coverage=Coverage(("weak_oracle", "determinism"), 2)),
        results=(ProbeResult(probe_id="weak_oracle", status=ProbeStatus.OK, sub_score=0.0, tasks_probed=1),),
    )

    assert _gate_on(clean, fail_on_gap=10.0) == EXIT_CLEAN
    assert _gate_on(clean, fail_on_finding=True) == EXIT_CLEAN


# ------------------------------------------------------- grouping and the zero caveat


def _render(report: Any) -> str:
    import io

    from rich.console import Console

    from bohrin.report.tty import render

    buf = io.StringIO()
    render(report, Console(file=buf, width=200, no_color=True))
    return buf.getvalue()


def _exploits_across(n: int) -> Any:
    """One operator, n tasks — the `scratchpad` shape: one defect, many tasks."""
    from bohrin.ir.evidence import Exploit
    from bohrin.ir.task import Candidate, Provenance, Verdict
    from bohrin.probes.base import ProbeResult, ProbeStatus
    from bohrin.scoring.gap import Coverage, GapScore

    findings = tuple(
        Exploit(
            task_id=str(i),
            candidate=Candidate(
                payload=f"echo {i}",
                provenance=Provenance(operator="identity_return", base="identity", detail="echoes the prompt"),
                ground=Ground.STRUCTURAL,
            ),
            verdict=Verdict(reward=1.0, passed=True),
            repro_args=f"--task {i} --operator identity_return",
        )
        for i in range(n)
    )
    base = _report_with_one_exploit("./t", isolation_none=True)
    return replace(
        base,
        gap=GapScore(score=50.0, coverage=Coverage(("weak_oracle", "determinism"), 2)),
        results=(
            ProbeResult(
                probe_id="weak_oracle", status=ProbeStatus.OK, sub_score=1.0, tasks_probed=n, findings=findings
            ),
        ),
        tasks_total=n,
    )


def test_one_operator_across_many_tasks_is_reported_once() -> None:
    """20 tasks failing one operator is one defect, not 20 findings.

    Before grouping, `scratchpad` printed six near-identical blocks and then "14 more" —
    so a second, different defect would have been pushed off the screen by the first
    one's repetitions.
    """
    out = _render(_exploits_across(20))

    assert out.count("EXPLOIT") == 1, "one root cause must produce one block"
    assert "identity_return accepted on 20 tasks" in out
    assert "example (task 0)" in out, "the worked example is the evidence and must survive"
    assert "more finding" not in out, "nothing is truncated away when it all fits in one group"


def test_a_single_finding_still_reads_naturally() -> None:
    """Grouping must not make the common one-task case read like a summary."""
    out = _render(_report_with_one_exploit("./t", isolation_none=True))

    assert "7: accepted empty_body" in out
    assert "submitted:" in out and "example (task" not in out


def test_two_different_operators_stay_two_findings() -> None:
    """The counterweight: grouping must not merge distinct defects."""
    from bohrin.ir.evidence import Exploit
    from bohrin.ir.task import Candidate, Provenance, Verdict
    from bohrin.probes.base import ProbeResult, ProbeStatus

    report = _exploits_across(3)
    other = Exploit(
        task_id="99",
        candidate=Candidate(
            payload="",
            provenance=Provenance(operator="empty_body", base="constant", detail="empty reply"),
            ground=Ground.STRUCTURAL,
        ),
        verdict=Verdict(reward=1.0, passed=True),
        repro_args="--task 99 --operator empty_body",
    )
    merged = replace(
        report,
        results=(
            ProbeResult(
                probe_id="weak_oracle",
                status=ProbeStatus.OK,
                sub_score=1.0,
                tasks_probed=4,
                findings=(*report.results[0].findings, other),
            ),
        ),
    )

    out = _render(merged)
    assert out.count("EXPLOIT") == 2
    assert "identity_return" in out and "empty_body" in out


def test_a_zero_score_says_what_it_does_not_prove() -> None:
    """False reassurance is a false accusation pointed the other way.

    A clean score bounds what the operators could construct. A reader who takes 0/100 as
    "sound" has been misled by omission, and the report is what they read.
    """
    from bohrin.probes.base import ProbeResult, ProbeStatus
    from bohrin.scoring.gap import Coverage, GapScore

    report = replace(
        _report_with_one_exploit("./t", isolation_none=True),
        gap=GapScore(score=0.0, coverage=Coverage(("weak_oracle", "determinism"), 2)),
        results=(
            ProbeResult(
                probe_id="weak_oracle",
                status=ProbeStatus.OK,
                sub_score=0.0,
                tasks_probed=5,
                detail={"operators": ["a", "b", "c", "d", "e", "f"]},
            ),
        ),
    )

    out = " ".join(_render(report).split())
    assert "not a proof that the verifier is sound" in out
    assert "6 model-free operators" in out, "the caveat must say how much was actually tried"


def test_a_nonzero_score_carries_no_caveat() -> None:
    """It applies to a clean result only; on a real finding it would be noise."""
    assert "not a proof" not in _render(_exploits_across(3))


def _one_probe_report(result: Any, score: float) -> Any:
    from bohrin.scoring.gap import Coverage, GapScore

    return replace(
        _report_with_one_exploit("./t", isolation_none=True),
        gap=GapScore(score=score, coverage=Coverage((result.probe_id,), 1)),
        results=(result,),
    )


def test_the_caveat_names_the_blind_spot_that_actually_exists() -> None:
    """The caveat tracks what Bohrin actually cannot do, and has been wrong twice by lagging
    behind a fix. Until 1.2 it named substring and last-number graders, caught since 1.1.0.
    Until 1.2.1 it named format-gated graders, which are now probed in the format the
    verifier itself accepted — so what remains is a task with no declared answer, where
    there is no baseline to learn a format from."""
    from bohrin.probes.base import ProbeResult, ProbeStatus

    clean = ProbeResult(
        probe_id="weak_oracle",
        status=ProbeStatus.OK,
        sub_score=0.0,
        tasks_probed=5,
        detail={"tasks_without_reference": 5},
    )
    out = " ".join(_render(_one_probe_report(clean, 0.0)).split())

    assert "not a proof that the verifier is sound" in out
    assert "no declared answer" in out, "the caveat must name the blind spot that remains"
    assert "substring" not in out and "last number" not in out, "it must not claim a gap Bohrin has closed"


def test_a_crash_is_not_headlined_as_an_acceptance() -> None:
    """Before 1.2 the headline counted every finding's task, so a result whose only finding
    was a crash printed "1 task accepts a known-wrong solution" beside a sub-score of 0."""
    from bohrin.ir.evidence import HarnessDisruption
    from bohrin.probes.base import ProbeResult, ProbeStatus
    from bohrin.scoring.interval import rate

    crash = HarnessDisruption(
        task_id="0", error="ValueError: boom", payload="x", operator="empty_body", repro_args="--task 0"
    )
    result = ProbeResult(
        probe_id="weak_oracle",
        status=ProbeStatus.OK,
        sub_score=0.0,
        tasks_probed=3,
        findings=(crash,),
        detail={"rate": rate(0, 3)},
    )
    out = " ".join(_render(_one_probe_report(result, 0.0)).split())

    assert "accepts a known-wrong" not in out
    assert "no accepted wrong solutions" in out


def test_the_gap_says_how_many_tasks_it_rests_on() -> None:
    """Measured before this existed: a synthetic environment where weak_oracle could measure
    2 of 20 tasks printed 50/100 at full probe coverage, with nothing to say so."""
    from bohrin.probes.base import ProbeResult, ProbeStatus
    from bohrin.scoring.interval import rate

    result = ProbeResult(
        probe_id="weak_oracle", status=ProbeStatus.OK, sub_score=1.0, tasks_probed=20, detail={"rate": rate(2, 2)}
    )
    out = " ".join(_render(_one_probe_report(result, 100.0)).split())

    assert "rests on: weak_oracle 2 of 2 tasks (95% CI 34–100%)" in out
    assert "(of 2 measured · 95% CI 34–100%)" in out


def test_a_task_id_with_spaces_survives_the_repro_command() -> None:
    """Task ids are taskset-supplied and routinely contain spaces.

    `glossary` names its tasks after people — "Ada Lovelace" — so an unquoted
    `--task Ada Lovelace` splits into two arguments and the printed command fails with
    `unrecognized arguments: Lovelace`. The 1.0.1 fix quoted the *target path* and a test
    pinned that; nothing covered the task id, and no environment had exercised it until
    an operator finally produced a finding on one that did.
    """
    from dataclasses import replace as dc_replace

    from bohrin.cli import _parser

    report = _report_with_one_exploit("./envs/t", isolation_none=False)
    exploit = report.results[0].findings[0]
    spaced = dc_replace(
        exploit,
        task_id="Ada Lovelace",
        repro_args=f"--task {shlex.quote('Ada Lovelace')} --operator empty_body",
    )
    printed = report.command_for(spaced)

    args = _parser().parse_args(shlex.split(printed)[1:])
    assert args.task == ["Ada Lovelace"], "an unquoted task id splits into two arguments"
