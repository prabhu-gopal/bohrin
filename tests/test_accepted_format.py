"""Graders gated on one answer format — the blind spot every clean report printed.

A verifier that reads only the last ``\\boxed{}`` rejects a bare payload for its
*presentation* before it ever judges its *content*, so it scores every operator's
submission zero and reads clean whether or not it is weak. Bohrin already discovers the
format such a verifier wants, because the baseline searches presentations of the known-good
answer until one is accepted. These tests pin the consequence: the wrong payloads are now
written in that same format.

The counterweights matter as much. A verifier gated on a format and *correct* about content
must stay clean, and a verifier that reads bare answers must not be sent a single extra
submission — every one costs a scoring call against somebody else's environment.
"""

from __future__ import annotations

import re

from bohrin.adapters.memory import MemorySource
from bohrin.config import ScanConfig
from bohrin.ir.evidence import Exploit
from bohrin.ir.task import Task
from bohrin.probes.base import ProbeResult
from bohrin.probes.weak_oracle import WeakOracleProbe

CONFIG = ScanConfig(concurrency=1, unsafe_local=True)

_BOXED = re.compile(r"\\boxed\{([^}]*)\}")


def _task() -> Task:
    return Task(id="0", prompt="Which letter?\nA. one\nB. two", reference="A", reward_fns=("g",))


def _exploited(result: ProbeResult) -> list[str]:
    return sorted({f.candidate.provenance.operator for f in result.findings if isinstance(f, Exploit)})


def _boxed_substring(task: Task, reply: str) -> float:
    """Gated on the format, weak inside it: the shape this test exists for."""
    match = _BOXED.search(reply)
    return float(match is not None and (task.reference or "") in match.group(1))


def _boxed_exact(task: Task, reply: str) -> float:
    """Gated on the format and correct inside it."""
    match = _BOXED.search(reply)
    return float(match is not None and match.group(1).strip() == (task.reference or ""))


def _bare_substring(task: Task, reply: str) -> float:
    """Reads bare answers, and is weak."""
    return float((task.reference or "") in reply)


async def test_a_format_gated_weak_grader_is_no_longer_clean() -> None:
    """Before this: 0 findings. Every payload was rejected for having no box at all."""
    result = await WeakOracleProbe().run(MemorySource([_task()], _boxed_substring), CONFIG)

    assert "false_negation" in _exploited(result)
    assert result.sub_score == 1.0
    # The finding is the payload in the verifier's own format, so the repro is runnable.
    exploit = next(f for f in result.findings if isinstance(f, Exploit))
    assert "\\boxed{" in exploit.candidate.payload
    assert result.detail["candidates_in_accepted_form"] > 0


async def test_a_format_gated_correct_grader_is_still_clean() -> None:
    """The counterweight: reaching a verifier is not the same as accusing it."""
    result = await WeakOracleProbe().run(MemorySource([_task()], _boxed_exact), CONFIG)

    assert _exploited(result) == []
    assert result.sub_score == 0.0
    # It was genuinely probed in its own format -- it simply rejected the wrong answers.
    assert result.detail["candidates_in_accepted_form"] > 0


async def test_a_grader_that_reads_bare_answers_is_sent_nothing_extra() -> None:
    """No format was required, so no re-rendered payload is worth a scoring call."""
    source = MemorySource([_task()], _bare_substring)

    result = await WeakOracleProbe().run(source, CONFIG)

    assert "false_negation" in _exploited(result)
    assert result.detail["candidates_in_accepted_form"] == 0


async def test_the_rendered_payload_never_becomes_the_answer() -> None:
    """Rendering must not turn a wrong payload into the right one: a verifier accepting its
    own answer back is not a defect, and reporting it would be the 1.0.1 launch blocker."""
    task = Task(id="0", prompt="What is 7 x 10?", reference="70", reward_fns=("g",))
    # Accepts the boxed answer only -- correct, and the baseline learns "boxed" from it.
    source = MemorySource([task], _boxed_exact)

    result = await WeakOracleProbe().run(source, CONFIG)

    assert _exploited(result) == []
    assert all(f.candidate.payload != "\\boxed{70}" for f in result.findings if isinstance(f, Exploit))
