"""degenerate_output: the replies a policy produces when generation goes wrong.

Its main job is to find graders that break on them — raise, recurse too deeply, or hang — which
Bohrin reports as a harness disruption. Before it, every payload was a short, well-behaved
string, so a grader that fails on long or malformed replies read as robust.
"""

from __future__ import annotations

from bohrin.adapters.base import RewardFunctionError
from bohrin.adapters.memory import MemorySource
from bohrin.config import ScanConfig
from bohrin.ir.evidence import Exploit, HarnessDisruption
from bohrin.ir.task import Candidate, Ground, Task, Verdict
from bohrin.mutate.operators import DegenerateOutput
from bohrin.probes.weak_oracle import WeakOracleProbe

ONLY = ScanConfig(unsafe_local=True, only_operators=frozenset({"degenerate_output"}))
BOTH = ScanConfig(unsafe_local=True, only_operators=frozenset({"degenerate_output", "empty_body"}))


def _tasks(reference: str | None = "42") -> list[Task]:
    return [
        Task(id=f"t{i}", prompt="What is six times seven?", reference=reference, reward_fns=("r",)) for i in range(2)
    ]


def test_the_payloads_stay_inside_what_a_policy_can_produce() -> None:
    payloads = [c.payload for c in DegenerateOutput().apply(_tasks()[0])]

    assert len(payloads) == 2
    assert all(len(p) <= DegenerateOutput.LOOP_CHARS for p in payloads)
    assert all("42" not in p for p in payloads), "a payload containing the answer could not be called wrong"


async def test_a_grader_that_recurses_on_nested_markup_is_reported() -> None:
    # Recursive descent spends a frame per grammar rule per nesting level: expression, term, factor.
    def expression(text: str) -> int:
        return term(text)

    def term(text: str) -> int:
        return factor(text)

    def factor(text: str) -> int:
        start = text.find("{")
        return 0 if start < 0 else 1 + expression(text[start + 1 :])

    def grade(task: Task, payload: str) -> float:
        expression(payload)
        return float(payload.strip() == task.reference)

    result = await WeakOracleProbe().run(MemorySource(_tasks(), grade), BOTH)

    crashes = [f for f in result.findings if isinstance(f, HarnessDisruption)]
    assert crashes and all(c.operator == "degenerate_output" for c in crashes)
    assert "RecursionError" in crashes[0].error
    assert result.sub_score == 0.0, "a crash accepted nothing and must not raise the acceptance score"


async def test_a_grader_that_raises_on_a_long_reply_is_reported() -> None:
    def grade(task: Task, payload: str) -> float:
        if len(payload) > 4096:
            raise ValueError("reply exceeds the parser's buffer")
        return float(payload.strip() == task.reference)

    result = await WeakOracleProbe().run(MemorySource(_tasks(), grade), BOTH)

    assert [f for f in result.findings if isinstance(f, HarnessDisruption)]


async def test_a_grader_accepting_anything_is_caught_where_an_answer_is_declared() -> None:
    result = await WeakOracleProbe().run(MemorySource(_tasks(), lambda _t, p: float(bool(p.strip()))), ONLY)

    exploits = [f for f in result.findings if isinstance(f, Exploit)]
    assert exploits and all(e.candidate.ground is Ground.STRUCTURAL for e in exploits)


async def test_a_length_grader_without_a_declared_answer_gets_a_lead_not_an_accusation() -> None:
    """A writing task graded on length may legitimately reward a long reply."""
    source = MemorySource(_tasks(reference=None), lambda _t, p: float(len(p) > 1000))

    result = await WeakOracleProbe().run(source, ONLY)

    assert not [f for f in result.findings if isinstance(f, Exploit)]
    assert result.unverified, "an accepted degenerate reply is still worth a human's attention"


async def test_a_spec_in_the_answer_field_gives_a_lead_not_an_accusation() -> None:
    """An instruction-following task stores its constraints where an answer would go. A repetition
    loop can satisfy "write at least 300 words", so a grader paying for it proves nothing."""
    spec = '{"func_name": "validate_word_count", "min_words": 300}'
    # Accepts its own spec too, so the baseline is green and the payloads are actually judged.
    source = MemorySource(_tasks(reference=spec), lambda _t, p: float(p.strip() == spec or len(p.split()) >= 300))

    result = await WeakOracleProbe().run(source, ONLY)

    assert not [f for f in result.findings if isinstance(f, Exploit)]
    assert result.unverified


class _WrappingSource:
    """A source that wraps a raising reward function the way the legacy adapter does."""

    def __init__(self) -> None:
        self._tasks = _tasks()

    def tasks(self):  # type: ignore[no-untyped-def]
        yield from self._tasks

    async def score(self, task: Task, candidate: Candidate) -> Verdict:
        # Only the reply cut off inside markup breaks this grader; the repetition loop scores
        # normally, which is what isolates the submission as the cause.
        if "\\boxed{" in candidate.payload:
            raise RewardFunctionError(
                "task refused. This usually means the reward functions read rollout state that only a "
                "live multi-turn rollout produces.",
                reward_error="Error calling reward function accuracy: 'NoneType' object has no attribute 'group'",
            )
        passed = candidate.payload.strip() == task.reference
        return Verdict(reward=float(passed), passed=passed)


async def test_a_crash_finding_quotes_the_graders_exception_not_the_adapters_guess() -> None:
    """Measured on a real sweep: every crash on one environment read "rollout state", which was
    not the cause. The submission was — other submissions to the same task scored normally."""
    result = await WeakOracleProbe().run(_WrappingSource(), ONLY)

    crashes = [f for f in result.findings if isinstance(f, HarnessDisruption)]
    assert crashes
    assert "'NoneType' object has no attribute 'group'" in crashes[0].error
    assert "rollout state" not in crashes[0].error
