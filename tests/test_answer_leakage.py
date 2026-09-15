"""Answer leakage: a task's declared answer written in its own prompt.

The probe calls no reward function, so the risk here is only one: reporting a coincidence as a
leak. Most of these tests are about the guards against that — whole-token matching, answers too
short to mean anything, and the control group that separates a leak from shared vocabulary. The
counterweights prove the guards did not simply switch the probe off.
"""

from __future__ import annotations

from bohrin.adapters.memory import MemorySource
from bohrin.config import ScanConfig
from bohrin.ir.evidence import AnswerInPrompt
from bohrin.ir.task import Task
from bohrin.probes.answer_leakage import MIN_INFORMATIVE_CHARS, AnswerLeakageProbe
from bohrin.probes.base import ProbeStatus
from bohrin.probes.weak_oracle import WeakOracleProbe
from bohrin.scoring.gap import verification_gap

CONFIG = ScanConfig(unsafe_local=True)


def _source(rows: list[tuple[str, str | None]]) -> MemorySource:
    tasks = [Task(id=f"t{i}", prompt=prompt, reference=ref, reward_fns=("r",)) for i, (prompt, ref) in enumerate(rows)]
    return MemorySource(tasks, lambda task, payload: float(payload.strip() == (task.reference or "")))


def _leaks(source: MemorySource, config: ScanConfig = CONFIG) -> tuple[list[AnswerInPrompt], dict[str, object]]:
    import asyncio

    result = asyncio.run(AnswerLeakageProbe().run(source, config))
    assert result.status is ProbeStatus.OK, result.reason
    return [f for f in result.findings if isinstance(f, AnswerInPrompt)], dict(result.detail)


def test_an_answer_written_in_its_own_prompt_is_reported_with_its_context() -> None:
    source = _source(
        [
            ("Who wrote the first published algorithm? Hint: it was Ada Lovelace.", "Ada Lovelace"),
            ("Who proposed the theory of general relativity?", "Albert Einstein"),
            ("Who discovered penicillin?", "Alexander Fleming"),
        ]
    )

    leaks, detail = _leaks(source)

    assert [leak.task_id for leak in leaks] == ["t0"]
    assert "Ada Lovelace" in leaks[0].excerpt, "the reader needs to see the match in its context"
    assert leaks[0].compared_with == 2, "both other tasks have different answers and form the control"
    assert detail["tasks_checked"] == 3
    assert detail["rate"] == {"affected": 1, "measured": 3, "interval_95": detail["rate"]["interval_95"]}  # type: ignore[index]


def test_it_calls_no_reward_function() -> None:
    """Static by design: it reads tasks the scoring probes cannot, at no cost to the environment."""
    source = _source([("The capital is Canberra.", "Canberra"), ("Largest ocean?", "Pacific")])

    _leaks(source)

    assert source.calls == 0


def test_shared_vocabulary_is_not_a_leak() -> None:
    """The control group. Every prompt lists the same options, so finding the answer among them
    identifies nothing: the same string sits in prompts whose answer is different."""
    options = "Choose one of: Paris, Berlin, Madrid."
    source = _source(
        [
            (f"Which city is the capital of France? {options}", "Paris"),
            (f"Which city is the capital of Germany? {options}", "Berlin"),
            (f"Which city is the capital of Spain? {options}", "Madrid"),
        ]
    )

    leaks, detail = _leaks(source)

    assert leaks == []
    assert detail["tasks_generic_overlap"] == 3


def test_a_match_inside_a_longer_word_is_not_a_leak() -> None:
    source = _source([("Write an important report about ports.", "port"), ("Name a sea.", "Baltic")])

    leaks, _ = _leaks(source)

    assert leaks == [], "'port' inside 'report' and 'ports' is not the answer written in the prompt"


def test_answers_too_short_to_mean_anything_are_not_checked() -> None:
    """``A``, ``12`` and ``yes`` occur in prompts by accident."""
    source = _source(
        [
            ("A) red B) green C) blue. Which is the colour of grass?", "B"),
            ("There are 12 eggs in a dozen. How many in two dozen?", "24"),
            ("Is the sky blue? Answer yes or no.", "yes"),
        ]
    )

    import asyncio

    result = asyncio.run(AnswerLeakageProbe().run(source, CONFIG))

    assert result.status is ProbeStatus.NOT_APPLICABLE
    assert result.findings == ()
    assert all(len(ref) < MIN_INFORMATIVE_CHARS for ref in ("B", "24", "yes"))


def test_a_copy_task_contains_its_answer_by_design() -> None:
    source = _source([("hello world", "hello world"), ("Name the planet we live on.", "Earth")])

    _, detail = _leaks(source)

    assert detail["tasks_prompt_is_answer"] == 1


def test_grader_state_is_not_an_answer() -> None:
    spec = '{"func_name": "verify_keywords", "keywords": ["alpha"]}'
    source = _source([(f"Follow this spec: {spec}", spec), ("Name the planet we live on.", "Earth")])

    leaks, detail = _leaks(source)

    assert leaks == []
    assert detail["tasks_not_checked"] == 1


def test_a_constant_answer_named_in_every_prompt_is_still_reported() -> None:
    """The shape of a real finding. Every task's graded answer was the name of the library each
    prompt was about, so there is no task with a different answer to form a control, and the
    answer is in the prompt on every task. Echoing the prompt scored full marks there."""
    source = _source(
        [
            ("In modelcontextprotocol/python-sdk, what language is the server written in?", "python"),
            ("Which language does modelcontextprotocol/python-sdk target?", "python"),
        ]
    )

    leaks, _ = _leaks(source)

    assert {leak.task_id for leak in leaks} == {"t0", "t1"}
    assert all(leak.compared_with == 0 for leak in leaks)


def test_the_repro_command_reproduces_the_finding() -> None:
    source = _source([("The answer is Canberra, obviously.", "Canberra"), ("Largest ocean?", "Pacific")])
    leaks, _ = _leaks(source)

    reproduced, _ = _leaks(source, ScanConfig(unsafe_local=True, only_tasks=frozenset({leaks[0].task_id})))

    assert [leak.task_id for leak in reproduced] == [leaks[0].task_id]
    assert "--probe answer_leakage" in leaks[0].repro_args


def test_matching_survives_case_and_unicode_width() -> None:
    source = _source([("ｔｈｅ ANSWER is ＣＡＮＢＥＲＲＡ", "Canberra"), ("Largest ocean?", "Pacific")])

    leaks, _ = _leaks(source)

    assert [leak.task_id for leak in leaks] == ["t0"]


def test_a_leak_never_moves_the_verification_gap() -> None:
    """Weight zero. An extractive task looks identical to a leak, so the number stays out."""
    import asyncio

    source = _source([("It is Canberra.", "Canberra"), ("Largest ocean?", "Pacific")])
    probes = [WeakOracleProbe(), AnswerLeakageProbe()]
    results = [asyncio.run(probe.run(source, CONFIG)) for probe in probes]

    assert results[1].findings, "the counterweight: the probe did find the leak"
    assert verification_gap(results, probes).score == 0.0
