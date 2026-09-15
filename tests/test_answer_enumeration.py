"""answer_enumeration: several different answers, with the declared one in the middle.

A grader that accepts the answer wherever it appears among several pays for a reply that also
asserts two wrong answers. The tests that matter most are the ones proving a correct grader is
not accused: one reading the first stated answer, one reading the last, and one comparing
numbers with a tolerance.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from bohrin.adapters.memory import MemorySource
from bohrin.config import ScanConfig
from bohrin.ir.evidence import Exploit
from bohrin.ir.task import Ground, Task
from bohrin.mutate.equivalence import provably_distinct
from bohrin.mutate.operators import AnswerEnumeration, _siblings
from bohrin.probes.weak_oracle import WeakOracleProbe

ONLY = ScanConfig(unsafe_local=True, only_operators=frozenset({"answer_enumeration"}))
_STATED = re.compile(r"(?:answer is|Answer:)\s*([^\s.]+(?:\.\d+)?)")


OPTIONS = "Which is it?\n\n(A) red\n(B) green\n(C) blue\n(D) yellow"


def _task(reference: str, prompt: str = "What is the value?") -> Task:
    return Task(id="t0", prompt=prompt, reference=reference, reward_fns=("r",))


async def _exploits(
    reference: str, grade: Callable[[str, str], bool], prompt: str = "What is the value?"
) -> list[Exploit]:
    source = MemorySource([_task(reference, prompt)], lambda task, payload: float(grade(payload, task.reference or "")))
    result = await WeakOracleProbe().run(source, ONLY)
    return [f for f in result.findings if isinstance(f, Exploit)]


@pytest.mark.parametrize(
    ("reference", "prompt", "expected"),
    [
        ("70", "", ("210", "350")),
        ("0", "", ("7", "14")),
        ("0.50", "", ("7.50", "14.50")),
        ("-3", "", ("4", "11")),
        ("B", OPTIONS, ("A", "C")),
        ("c", OPTIONS, ("B", "D")),
        ("B", "Option A: x\nOption B: y\nOption C: z", ("A", "C")),
    ],
)
def test_siblings_are_written_like_the_answer_and_provably_different(
    reference: str, prompt: str, expected: tuple[str, str]
) -> None:
    siblings = _siblings(reference, prompt)

    assert siblings == expected
    assert all(provably_distinct(s, reference) for s in expected)


@pytest.mark.parametrize(
    ("reference", "prompt"),
    [
        ("Paris", ""),
        ("x + 1", ""),
        ("[1, 2]", ""),
        ("", ""),
        ("I cannot help with that.", ""),
        ("D", OPTIONS),  # the last option: nothing offered after it
        ("A", OPTIONS),  # the first option: nothing offered before it
        ("B", "Pick the best answer."),  # no options listed, so no offered sibling is known
    ],
)
def test_it_stays_silent_where_no_sibling_can_be_proven_different(reference: str, prompt: str) -> None:
    assert list(AnswerEnumeration().apply(_task(reference, prompt))) == []


def test_the_declared_answer_is_never_first_or_last() -> None:
    for candidate in AnswerEnumeration().apply(_task("70")):
        stated = _STATED.findall(candidate.payload)
        assert stated == ["210", "70", "350"]
        assert candidate.ground is Ground.INVARIANT


async def test_a_grader_accepting_the_answer_among_several_is_caught() -> None:
    exploits = await _exploits("70", lambda reply, ref: ref in _STATED.findall(reply))

    assert exploits, "a grader paying for the answer anywhere among several must be reported"
    assert all(e.candidate.provenance.operator == "answer_enumeration" for e in exploits)


async def test_a_grader_reading_the_first_stated_answer_is_not_accused() -> None:
    def first(reply: str, ref: str) -> bool:
        stated = _STATED.findall(reply)
        return bool(stated) and stated[0] == ref

    assert await _exploits("70", first) == []


async def test_a_grader_reading_the_last_stated_answer_is_not_accused() -> None:
    """Taking the last answer is a legitimate design: a model may correct itself."""

    def last(reply: str, ref: str) -> bool:
        stated = _STATED.findall(reply)
        return bool(stated) and stated[-1] == ref

    assert await _exploits("70", last) == []


@pytest.mark.parametrize("reference", ["1000000", "0.5", "-1"])
async def test_a_tolerant_numeric_grader_is_not_accused(reference: str) -> None:
    """A sibling inside a correct grader's tolerance would *be* the answer to it. The siblings
    are far enough away that a 1% relative tolerance, applied to any stated answer, still only
    ever matches the declared one — so only the any-of-several shape can accept."""

    def close_to_first(reply: str, ref: str) -> bool:
        stated = _STATED.findall(reply)
        try:
            value, want = float(stated[0]), float(ref)
        except (IndexError, ValueError):
            return False
        return abs(value - want) <= max(1e-6, 0.01 * abs(want))

    assert await _exploits(reference, close_to_first) == []


async def test_a_multiple_choice_grader_taking_the_first_label_is_not_accused() -> None:
    def first_label(reply: str, ref: str) -> bool:
        match = re.search(r"\b([A-D])\b", reply)
        return match is not None and match.group(1) == ref

    assert await _exploits("B", first_label, OPTIONS) == []


@pytest.mark.parametrize("reference", ["B", "C", "D"])
async def test_a_grader_taking_the_last_valid_option_letter_is_not_accused(reference: str) -> None:
    """The shape of a real public grader: the last standalone A-D in the reply. Before siblings were
    restricted to offered options, ``C … D … E`` read as ``D`` here and it was accused on every task
    whose answer was ``D``."""

    def last_valid(reply: str, ref: str) -> bool:
        found = re.findall(r"(?<![A-Z])([ABCD])(?=[\s.,)\]}]|$)", reply)
        return bool(found) and found[-1] == ref

    assert await _exploits(reference, last_valid, OPTIONS) == []


@pytest.mark.parametrize("reference", ["70", "0", "5", "-3"])
async def test_a_grader_whose_number_pattern_drops_the_sign_is_not_accused(reference: str) -> None:
    """``\\d+`` reads ``-70`` as ``70``. A sibling below the answer would hand such a last-number
    grader the declared answer back."""

    def last_digits(reply: str, ref: str) -> bool:
        found = re.findall(r"\d+", reply)
        return bool(found) and found[-1] == ref.lstrip("-")

    assert await _exploits(reference, last_digits) == []


async def test_an_any_of_several_multiple_choice_grader_is_still_caught() -> None:
    """The counterweight for the letter rules: they must not have switched the operator off."""
    exploits = await _exploits("B", lambda reply, ref: ref in re.findall(r"\b([A-D])\b", reply), OPTIONS)

    assert exploits
