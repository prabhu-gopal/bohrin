"""A clean result that rests on tasks with no declared answer says so.

Most operators need a known-good answer: without one there is nothing to contradict and
nothing to be provably distinct from, so only the payloads needing no answer at all can be
submitted -- an empty reply, a refusal, the prompt echoed back. A verifier that rejects
those three has been asked very little, and "no accepted wrong solutions (of 100 measured)"
reads like the opposite.

Measured on the 2026-09-13 sweep of 57 public environments: 5 of the 16 that could be
measured declared no answer on any task, so nearly a third of the clean results were this
weaker kind with nothing in the headline to separate them.
"""

from __future__ import annotations

import io

from rich.console import Console

from bohrin.adapters.memory import MemorySource
from bohrin.config import ScanConfig
from bohrin.ir.task import Task
from bohrin.probes.weak_oracle import WeakOracleProbe
from bohrin.report.model import Report
from bohrin.report.tty import render
from bohrin.scoring.gap import Coverage, GapScore

CONFIG = ScanConfig(concurrency=1, unsafe_local=True)

_NOTE = "no task here declares an answer"


def _rejects_everything(_task: Task, _reply: str) -> float:
    return 0.0


def _rendered(result: object) -> str:
    report = Report(
        target="./envs/t",
        adapter="verifiers_legacy",
        gap=GapScore(score=0.0, coverage=Coverage(measured=("weak_oracle",), total=1)),
        results=(result,),  # type: ignore[arg-type]
        tasks_total=3,
    )
    buf = io.StringIO()
    render(report, Console(file=buf, width=200, no_color=True))
    return " ".join(buf.getvalue().split())


async def test_a_clean_with_no_declared_answers_is_qualified() -> None:
    """Before this: the same headline as a clean backed by a known-good answer."""
    tasks = [Task(id=str(i), prompt=f"Describe case {i}.", reward_fns=("g",)) for i in range(3)]

    result = await WeakOracleProbe().run(MemorySource(tasks, _rejects_everything), CONFIG)

    assert result.detail["tasks_without_reference"] == result.detail["tasks_measurable"] == 3
    assert _NOTE in _rendered(result)


async def test_a_clean_backed_by_declared_answers_is_not_qualified() -> None:
    """The counterweight: where answers exist, every operator ran and the note would be a lie."""
    tasks = [Task(id=str(i), prompt=f"What is {i} + 1?", reference=str(i + 1), reward_fns=("g",)) for i in range(3)]

    result = await WeakOracleProbe().run(MemorySource(tasks, lambda t, r: float(r.strip() == t.reference)), CONFIG)

    assert result.detail["tasks_without_reference"] == 0
    assert _NOTE not in _rendered(result)


async def test_a_finding_is_never_qualified_this_way() -> None:
    """The note belongs to a clean result only: an exploit was found, so nothing was missed
    for want of an answer."""
    tasks = [Task(id="0", prompt="Say anything.", reward_fns=("g",))]

    result = await WeakOracleProbe().run(MemorySource(tasks, lambda _t, reply: 1.0 if reply.strip() else 0.0), CONFIG)

    assert result.findings
    assert _NOTE not in _rendered(result)
