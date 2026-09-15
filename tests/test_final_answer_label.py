"""``Final Answer: X`` is a presentation Bohrin can now learn.

Found on the 2026-09-15 sweep. A public multiple-choice environment's parser accepts exactly one
shape, ``Final Answer: X`` -- the format its own published system prompt asks for. Scored
directly with Bohrin uninstalled, that rendering earned full marks on 3 of 3 tasks and the bare
answer, ``\\boxed{}``, an answer tag, ``Answer:`` and a think-then-answer reply all earned 0.
With no such relation the baseline never found the format, and all 10 sampled tasks read as
not measurable.

The graders below reproduce that parser exactly. The first one is also weak, which this change is
what lets Bohrin see: once the format is known, wrong payloads are re-sent in it, and
``Final Answer: B is not the answer.`` parses as ``B``. The counterweight is a strict grader
reading the same format, which must stay clean.
"""

from __future__ import annotations

import re

from bohrin.adapters.memory import MemorySource
from bohrin.config import ScanConfig
from bohrin.ir.evidence import Exploit
from bohrin.ir.task import Task
from bohrin.probes.base import ProbeResult, ProbeStatus
from bohrin.probes.weak_oracle import WeakOracleProbe
from bohrin.relations import discover
from bohrin.relations.builtin import FinalAnswerLabel

CONFIG = ScanConfig(concurrency=1, unsafe_local=True)


def _task() -> Task:
    # The prompt deliberately does not start with a letter A-F, so an echoed prompt cannot
    # parse as an answer and blur what these tests measure.
    return Task(id="0", prompt="Pick the most realistic option.", reference="B", reward_fns=("final_answer",))


def _label_parser(task: Task, reply: str) -> float:
    """The environment's parser, verbatim: the first A-F letter after the label."""
    match = re.search(r"Final Answer:\s*([A-F])", reply.strip(), re.IGNORECASE | re.DOTALL)
    return float(match is not None and match.group(1).upper() == (task.reference or "").strip().upper())


def _strict_label(task: Task, reply: str) -> float:
    """The same format, read strictly: the whole reply must be the label and one letter."""
    match = re.fullmatch(r"\s*Final Answer:\s*([A-F])\s*", reply)
    return float(match is not None and match.group(1).upper() == (task.reference or "").strip().upper())


def _exploited(result: ProbeResult) -> set[str]:
    return {f.candidate.provenance.operator for f in result.findings if isinstance(f, Exploit)}


def test_the_label_is_rendered_around_the_answer_unchanged() -> None:
    relation = FinalAnswerLabel()
    assert relation.render("B") == "Final Answer: B"
    assert relation.render("  42  ") == "Final Answer: 42"
    assert relation.render("") is None
    assert relation.render("   ") is None


def test_the_relation_is_appended_so_earlier_audits_keep_their_search_order() -> None:
    ids = [r.id for r in discover()]
    assert "final_answer_label" in ids
    assert ids.index("final_answer_label") > ids.index("braced_sqrt_argument")


async def test_a_grader_that_only_reads_the_label_is_now_measured() -> None:
    """Before: not measured, because no rendering of the answer reached full marks."""
    result = await WeakOracleProbe().run(MemorySource([_task()], _strict_label), CONFIG)

    assert result.status is ProbeStatus.OK
    assert result.detail["rate"]["measured"] == 1


async def test_a_label_parser_that_accepts_a_denial_is_caught() -> None:
    result = await WeakOracleProbe().run(MemorySource([_task()], _label_parser), CONFIG)

    assert "false_negation" in _exploited(result)
    payloads = {f.candidate.payload for f in result.findings if isinstance(f, Exploit)}
    assert "Final Answer: B is not the answer." in payloads


async def test_a_strict_label_grader_is_not_accused() -> None:
    """The counterweight: learning the format must not make a correct grader look weak."""
    result = await WeakOracleProbe().run(MemorySource([_task()], _strict_label), CONFIG)

    assert _exploited(result) == set()
    assert result.sub_score == 0.0
