"""Rubrics that pay past their own declared full marks.

A reply counts as accepted when its reward reaches full marks, and full marks are read
from the rubric's weights -- which assume every reward function returns 0 to 1. Found by
hand-verifying the first index sweep: two public environments pay on other scales, and
Bohrin reported both as exploited.

* One sums five criteria scored 0-3, so a reply is worth up to 15. A prompt echo scoring
  12 of 15 cleared the bar of 1 and was reported as full marks.
* One averages 1-5 ratings, so almost any parseable reply scores at least 1. It is a
  questionnaire whose reward is a trait score, not correctness, and every reply "passed".

Bohrin cannot read a rubric's true scale, so a task on which any reply paid past full
marks is excluded from measurement, and what it accepted is reported as a lead. The last
tests are the counterweights: an ordinary 0-1 grader is measured exactly as before.
"""

from __future__ import annotations

from bohrin.adapters.memory import MemorySource
from bohrin.config import ScanConfig
from bohrin.ir.evidence import Exploit
from bohrin.ir.task import Task
from bohrin.probes.base import ProbeResult, ProbeStatus
from bohrin.probes.weak_oracle import WeakOracleProbe

CONFIG = ScanConfig(concurrency=1, unsafe_local=True)


def _exploits(result: ProbeResult) -> list[Exploit]:
    return [f for f in result.findings if isinstance(f, Exploit)]


def _rating_mean(_task: Task, reply: str) -> float:
    """A questionnaire score: any reply that says anything averages around the midpoint."""
    return 2.5 if reply.strip() else 0.0


def _criteria_sum(task: Task, reply: str) -> float:
    """Five criteria, 0-3 each. The declared answer earns all 15; anything else earns 1."""
    if not reply.strip():
        return 0.0
    return 15.0 if reply.strip() == (task.reference or "") else 1.0


async def test_a_rating_scale_is_not_read_as_full_marks() -> None:
    """Before this: ``identity_return`` and ``refusal`` reported as exploited on every task."""
    tasks = [Task(id=str(i), prompt=f"Rate statement {i} from 1 to 5.", reward_fns=("raw",)) for i in range(4)]
    source = MemorySource(tasks, _rating_mean, full_marks=1.0)

    result = await WeakOracleProbe().run(source, CONFIG)

    assert _exploits(result) == []
    # Nothing left to measure is "not measured", never "clean".
    assert result.status is ProbeStatus.ERROR
    assert result.sub_score is None
    assert result.detail["tasks_scale_unknown"] == 4
    # What it accepted is still visible, as a lead.
    assert result.unverified


async def test_a_reference_scoring_past_full_marks_excludes_its_task() -> None:
    """Before this: a prompt echo scoring 1 of 15 was an exploit, because 1 >= the weight."""
    task = Task(id="0", prompt="Write a short story about Mars.", reference="THE STORY", reward_fns=("antislop",))
    source = MemorySource([task], _criteria_sum, full_marks=1.0)

    result = await WeakOracleProbe().run(source, CONFIG)

    assert _exploits(result) == []
    assert result.detail["tasks_scale_unknown"] == 1


async def test_only_the_tasks_off_scale_are_excluded() -> None:
    """One task pays past full marks and one does not: the second is still measured."""
    tasks = [
        Task(id="off", prompt="Rate this.", reference="A", reward_fns=("g",)),
        Task(id="on", prompt="Which letter?", reference="B", reward_fns=("g",)),
    ]

    def grader(task: Task, reply: str) -> float:
        if task.id == "off":
            return 3.0 if reply.strip() else 0.0
        return float("B" in reply)  # substring: a real weakness, on the ordinary scale

    result = await WeakOracleProbe().run(MemorySource(tasks, grader, full_marks=1.0), CONFIG)

    assert result.status is ProbeStatus.OK
    assert {f.task_id for f in _exploits(result)} == {"on"}
    assert result.detail["tasks_scale_unknown"] == 1
    assert result.detail["rate"]["measured"] == 1
    assert result.sub_score == 1.0


async def test_an_ordinary_grader_is_measured_exactly_as_before() -> None:
    """The counterweight: a 0-1 grader never trips the guard, weak or not."""
    task = Task(id="0", prompt="Which letter?", reference="B", reward_fns=("g",))
    source = MemorySource([task], lambda _t, reply: float("B" in reply), full_marks=1.0)

    result = await WeakOracleProbe().run(source, CONFIG)

    assert "false_negation" in {f.candidate.provenance.operator for f in _exploits(result)}
    assert result.detail["tasks_scale_unknown"] == 0
