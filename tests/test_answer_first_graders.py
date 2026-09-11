"""Graders that read the *start* of a reply, which ``false_negation`` could not reach.

Found by the hand-verification pass over the first index sweep, which checks a sample of
*clean* results as well as flagged ones. Two public multiple-choice environments read clean
at 0 of 100 tasks. Called directly, with Bohrin out of the loop, both graders paid full
reward for ``A is not the answer.`` on 100 of 100 tasks:

* one extracts ``\\boxed{}`` content -- falling back to the whole reply when there is none --
  and then checks it ``startswith`` the declared letter;
* one takes the first standalone capitalised token when no ``ANSWER:``-style pattern
  matches.

Every denial Bohrin wrote began with ``The``, so neither grader ever saw the answer first.
The tests below reproduce both shapes as synthetic graders, and fail the build if the
recall is lost again. The last test is the counterweight: a correct grader is untouched.
"""

from __future__ import annotations

import re

from bohrin.adapters.memory import MemorySource
from bohrin.config import ScanConfig
from bohrin.ir.evidence import Exploit
from bohrin.ir.task import Ground, Task
from bohrin.mutate.operators import FalseNegation
from bohrin.probes.base import ProbeResult
from bohrin.probes.weak_oracle import WeakOracleProbe

CONFIG = ScanConfig(concurrency=1, unsafe_local=True)

_BOXED = re.compile(r"\\boxed\{([^}]*)\}")


def _exploited(result: ProbeResult) -> list[str]:
    return sorted({f.candidate.provenance.operator for f in result.findings if isinstance(f, Exploit)})


_QUESTION = "Which is correct?\nA. one\nB. two\nC. three\nD. four"


def _mcq(letter: str) -> Task:
    return Task(id="0", prompt=_QUESTION, reference=letter, reward_fns=("g",))


def _startswith_after_boxed(task: Task, reply: str) -> float:
    """Boxed content if any, else the raw reply -- then a prefix test."""
    match = _BOXED.search(reply)
    extracted = match.group(1) if match else reply
    return float(extracted.strip().startswith(task.reference or "\0"))


def _first_label(task: Task, reply: str) -> float:
    """The first standalone one-to-four-letter capitalised token."""
    tokens = re.findall(r"\b([A-Z]{1,4})\b", reply.strip().upper())
    return float(bool(tokens) and tokens[0] == (task.reference or "").upper())


def _exact(task: Task, reply: str) -> float:
    return float(reply.strip() == (task.reference or ""))


async def test_a_prefix_grader_is_caught() -> None:
    """Before 1.2.1: read clean, on a grader that pays for ``A is not the answer.``."""
    result = await WeakOracleProbe().run(MemorySource([_mcq("A")], _startswith_after_boxed), CONFIG)

    assert "false_negation" in _exploited(result)


async def test_a_first_label_grader_is_caught() -> None:
    """Before 1.2.1: read clean. ``The answer is not A.`` gives ``THE`` as the first token."""
    result = await WeakOracleProbe().run(MemorySource([_mcq("A")], _first_label), CONFIG)

    assert "false_negation" in _exploited(result)


def test_every_denial_contradicts_rather_than_restates_the_answer() -> None:
    """Each form names the declared answer and denies it, and none collides with it."""
    candidates = list(FalseNegation().apply(_mcq("A")))

    assert len(candidates) == len(FalseNegation._FORMS)
    assert any(c.payload.startswith("A ") for c in candidates), "no form puts the answer first"
    assert all(c.ground is Ground.INVARIANT for c in candidates)
    assert all(" not " in c.payload or "wrong" in c.payload for c in candidates)


async def test_a_correct_grader_is_not_accused() -> None:
    """The counterweight: exact match rejects every denial, answer-first or not."""
    result = await WeakOracleProbe().run(MemorySource([_mcq("A")], _exact), CONFIG)

    assert _exploited(result) == []
