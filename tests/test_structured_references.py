"""A declared "answer" that is a JSON object is grader state, not a reply.

Found by hand-verifying the 2026-09-13 sweep. An instruction-following environment declares
``{"func_name": "verify_postscript", "postscript_marker": "Addendum:", ...}`` in its answer
field — a constraint spec its grader dispatches on. ``false_negation`` submitted ``The answer
is not {...}.`` and claimed an invariant ground; ``constant_return`` submitted ``0`` and
claimed a differential one. Both rest on the spec being the answer, which it is not. Of 17
tasks flagged there, 8 rested on nothing else. The spec even passed its own check — it
contains the marker it asks for — which is why the baseline took it for a confirmed answer.

The counterweights matter more than the fix: grounds needing no answer must survive on the
same task, and a JSON *array* or scalar must stay an answer.
"""

from __future__ import annotations

import json

import pytest

from bohrin.adapters.memory import MemorySource
from bohrin.config import ScanConfig
from bohrin.ir.evidence import Exploit, Unverified
from bohrin.ir.task import Task
from bohrin.mutate.equivalence import reads_as_structured_state
from bohrin.probes.base import ProbeResult, ProbeStatus
from bohrin.probes.ground_truth_rejected import GroundTruthRejectedProbe
from bohrin.probes.weak_oracle import WeakOracleProbe

CONFIG = ScanConfig(concurrency=1, unsafe_local=True)

_SPEC = json.dumps({"func_name": "verify_postscript", "N": None, "postscript_marker": "Addendum:"})


def _has_marker(_task: Task, reply: str) -> float:
    """A correct constraint grader: the reply must contain the postscript marker."""
    return float("Addendum:" in reply)


def _exploited(result: ProbeResult) -> set[str]:
    return {f.candidate.provenance.operator for f in result.findings if isinstance(f, Exploit)}


def _leads(result: ProbeResult) -> set[str]:
    return {u.candidate.provenance.operator for u in result.unverified if isinstance(u, Unverified)}


@pytest.mark.parametrize(
    ("text", "is_state"),
    [
        (_SPEC, True),
        ('  {"remaining_words": ["DIRT"], "answer": [{"group": "X"}]}  ', True),
        ("{}", True),
        ("[[0]]", False),  # a grid is an answer
        ('["A", "B"]', False),
        ("70", False),
        ("{not json", False),
        ("\\boxed{42}", False),  # braces, but not a JSON object
        ("The answer is {x}", False),
    ],
)
def test_only_a_json_object_reads_as_state(text: str, is_state: bool) -> None:
    assert reads_as_structured_state(text) is is_state


def test_a_long_spec_is_still_state() -> None:
    """No size limit: ``False`` keeps the grounds, so a limit would fail in the unsafe direction.

    Real specs embed the task's own prompt and run past any limit sized for short answers.
    """
    spec = json.dumps({"func_name": "verify_keywords", "original_prompt": "Write an essay. " * 800})
    assert len(spec) > 10_000
    assert reads_as_structured_state(spec) is True


async def test_a_denial_of_a_constraint_spec_is_not_an_exploit() -> None:
    """Before: ``false_negation`` and ``constant_return`` reported exploited on a correct grader."""
    task = Task(id="614", prompt="Write a note. End with a postscript.", reference=_SPEC, reward_fns=("marker",))

    result = await WeakOracleProbe().run(MemorySource([task], _has_marker), CONFIG)

    assert not _exploited(result) & {"false_negation", "constant_return"}
    # Still submitted, and still visible: the spec contains the marker, so the denial is
    # accepted -- which is a lead for a human, never a score.
    assert "false_negation" in _leads(result)
    assert result.detail["grounds_withdrawn"] > 0


async def test_grounds_needing_no_answer_survive_on_the_same_task() -> None:
    """The counterweight: a grader paying for an echo is still caught where the answer is a spec."""
    task = Task(
        id="0",
        prompt="Write a note and end it with Addendum: thanks.",
        reference=_SPEC,
        reward_fns=("marker",),
    )

    result = await WeakOracleProbe().run(MemorySource([task], _has_marker), CONFIG)

    assert "identity_return" in _exploited(result), "the prompt contains the marker; echoing it is still no answer"
    assert result.sub_score == 1.0


async def test_a_grid_answer_keeps_its_reference_grounds() -> None:
    """The other counterweight: JSON arrays are answers, and a substring grader is still caught."""
    task = Task(id="0", prompt="Solve the grid.", reference="[[1, 2], [3, 4]]", reward_fns=("contains",))
    source = MemorySource([task], lambda t, reply: float((t.reference or "") in reply))

    result = await WeakOracleProbe().run(source, CONFIG)

    assert "false_negation" in _exploited(result)
    assert result.detail["grounds_withdrawn"] == 0


async def test_a_spec_is_not_submitted_as_ground_truth() -> None:
    """Before: "the declared answer was rejected" on every task whose answer field is a spec."""
    task = Task(id="0", prompt="Write a note.", reference=_SPEC, reward_fns=("marker",))
    source = MemorySource([task], lambda _t, _reply: 0.0)

    result = await GroundTruthRejectedProbe().run(source, CONFIG)

    assert result.status is ProbeStatus.NOT_APPLICABLE
    assert not result.findings
    assert "JSON object" in (result.reason or "")


async def test_ground_truth_rejected_still_runs_on_the_other_tasks() -> None:
    tasks = [
        Task(id="spec", prompt="Write a note.", reference=_SPEC, reward_fns=("r",)),
        Task(id="real", prompt="What is 7 x 10?", reference="70", reward_fns=("r",)),
    ]
    source = MemorySource(tasks, lambda _t, _reply: 0.0)

    result = await GroundTruthRejectedProbe().run(source, CONFIG)

    assert result.status is ProbeStatus.OK
    assert {getattr(f, "task_id", None) for f in result.findings} == {"real"}
