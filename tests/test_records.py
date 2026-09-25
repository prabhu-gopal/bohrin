"""The one-line summaries of the records a check produces: each states what was found, never more.

A summary is what gets quoted out of context, so each is held to its exact wording here.
"""

from __future__ import annotations

from bohrin.ir.evidence import AnswerInPrompt, Exploit, Flake, GroundTruthRejected, HarnessDisruption
from bohrin.ir.task import Candidate, Ground, Provenance, Source, Verdict


def _candidate() -> Candidate:
    return Candidate(
        Source("def f():\n    pass\n"), Provenance("drop_side_effect", "reference", "emptied"), Ground.STRUCTURAL
    )


def test_an_exploit_names_the_task_the_probe_and_the_reward() -> None:
    exploit = Exploit("t1", _candidate(), Verdict(reward=1.0, passed=True))
    assert exploit.summary == "t1: accepted drop_side_effect (reward 1)"


def test_a_flake_states_every_reward_and_its_spread() -> None:
    flake = Flake("t1", (1.0, 0.0, 1.0))
    assert flake.spread == 1.0
    assert flake.summary == "t1: identical submission scored 1, 0, 1"


def test_ground_truth_rejected_states_the_search_budget_not_a_verdict() -> None:
    record = GroundTruthRejected("t1", "def f():\n    return 1\n", ("comment_free", "reformatted"))
    assert record.summary == "t1: no rendering of the declared answer was accepted (2 tried)"
    assert "broken" not in record.summary and "wrong" not in record.summary


def test_a_harness_disruption_quotes_a_bounded_error() -> None:
    record = HarnessDisruption("t1", "x" * 500, Source("pass\n"))
    assert record.summary.startswith("t1: the verifier failed on a well-formed submission (")
    assert len(record.summary) < 150, "an error message never floods a report"


def test_an_answer_in_the_prompt_says_where_it_was_found_only() -> None:
    record = AnswerInPrompt("t1", "return 42", "…just return 42…")
    assert record.summary == "t1: the declared answer appears verbatim in the prompt"
