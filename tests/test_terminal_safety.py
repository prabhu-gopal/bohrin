"""Text from a taskset cannot drive the terminal, and reproduction commands still reproduce.

Bohrin prints task ids, prompts, declared answers, payloads and grader errors taken from the
taskset under audit. Before this was guarded, a task id carrying ``\\x1b[2J`` reached the
terminal intact on three report lines: a hostile taskset could clear the screen, move the
cursor and erase the line reporting its own exploit, or print a forged one.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from io import StringIO

import pytest
from rich.console import Console

from bohrin._text import safe, shell_arg, visible
from bohrin.ir.evidence import Exploit, HarnessDisruption
from bohrin.ir.task import Candidate, Ground, Provenance, Verdict
from bohrin.probes.base import ProbeResult, ProbeStatus
from bohrin.probes.weak_oracle import WeakOracleProbe
from bohrin.report.model import Report
from bohrin.report.tty import render
from bohrin.scoring.gap import verification_gap

#: Clear screen, cursor up and erase line, a window-title OSC, a hyperlink, a bell, a carriage
#: return, a C1 control, and a right-to-left override.
HOSTILE = "t\x1b[2J\x1b[1A\x1b[2K\x1b]0;title\x07\x1b]8;;https://x.example\x07\rok\x85\u202egnp.exe"


def _control_bytes(text: str) -> list[str]:
    return [c for c in text if (ord(c) < 0x20 and c != "\n") or 0x7F <= ord(c) <= 0x9F or c == "\u202e"]


def _report_with_hostile_text() -> Report:
    candidate = Candidate(
        payload=f"The answer is {HOSTILE}",
        provenance=Provenance(operator="false_negation", base="reference", detail=f"denies {HOSTILE}"),
        ground=Ground.INVARIANT,
    )
    findings = (
        Exploit(
            task_id=HOSTILE,
            candidate=candidate,
            verdict=Verdict(reward=1.0, passed=True),
            repro_args=f"--task {shell_arg(HOSTILE)} --operator false_negation",
        ),
        HarnessDisruption(
            task_id=HOSTILE,
            error=f"ValueError: {HOSTILE}",
            payload=HOSTILE,
            operator="empty_body",
            repro_args=f"--task {shell_arg(HOSTILE)} --operator empty_body",
        ),
    )
    result = ProbeResult(
        probe_id="weak_oracle", status=ProbeStatus.OK, tasks_probed=1, sub_score=100.0, findings=findings
    )
    return Report(
        target=f"./envs/{HOSTILE}",
        adapter="memory",
        gap=verification_gap([result], [WeakOracleProbe()]),
        results=(result,),
        tasks_total=1,
    )


def _rendered(report: Report) -> str:
    buffer = StringIO()
    render(report, Console(file=buffer, width=400, no_color=True))
    return buffer.getvalue()


def test_no_control_character_from_the_taskset_reaches_the_terminal() -> None:
    out = _rendered(_report_with_hostile_text())

    assert _control_bytes(out) == [], "a taskset string was printed as a live terminal sequence"


def test_the_hostile_text_is_shown_rather_than_hidden() -> None:
    """Neutralising must not mean deleting: the reader should see that something was there."""
    out = _rendered(_report_with_hostile_text())

    assert "\\x1b[2J" in out
    assert "\\xe2\\x80\\xae" in out, "the right-to-left override is displayed as its bytes"


def test_ordinary_text_is_unchanged() -> None:
    for text in ["Canberra", "The answer is not 70.", "naïve café 中文", "[bold]not markup[/bold]", "a\\b"]:
        assert visible(text) == text
    assert safe("[bold]x[/bold]") != "[bold]x[/bold]", "Rich markup is still escaped"


@pytest.mark.parametrize(
    "text",
    ["plain", "has space", "it's", "a\\b", "", "-leading-dash", "naïve"],
)
def test_ordinary_arguments_are_quoted_exactly_as_before(text: str) -> None:
    """No existing reproduction command changes."""
    assert shell_arg(text) == shlex.quote(text)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is not installed")
@pytest.mark.parametrize(
    "text",
    [HOSTILE, "tab\there", "new\nline", "quote ' and \\ backslash\x1b[0m", "\x00nul", "café\x85"],
)
def test_a_pasted_reproduction_command_reproduces_the_exact_task_id(text: str) -> None:
    """ANSI-C quoting decodes back to the original bytes in a real shell."""
    if "\x00" in text:
        pytest.skip("a shell argument cannot carry a NUL byte")
    got = subprocess.run(["bash", "-c", f"printf %s {shell_arg(text)}"], capture_output=True, check=True).stdout

    assert got == text.encode("utf-8")


def test_the_reproduction_command_carries_no_raw_control_character() -> None:
    """The target path comes from the user, and it is quoted the same way."""
    report = _report_with_hostile_text()

    for finding in report.results[0].findings:
        assert _control_bytes(report.command_for(finding)) == []
