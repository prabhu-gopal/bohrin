"""Findings: the records a check produces about a verifier."""

from __future__ import annotations

from dataclasses import dataclass

from bohrin.ir.task import Candidate, Payload, Verdict


@dataclass(frozen=True, slots=True)
class Exploit:
    """A known-wrong candidate that the verifier accepted.

    Constructed only from a candidate whose ``ground`` is set. An accepted candidate whose
    wrongness could not be established is an :class:`Unverified` lead instead — a finding
    must never blur the two.
    """

    task_id: str
    candidate: Candidate
    verdict: Verdict

    @property
    def summary(self) -> str:
        return f"{self.task_id}: accepted {self.candidate.provenance.operator} (reward {self.verdict.reward:g})"


@dataclass(frozen=True, slots=True)
class Unverified:
    """A candidate the verifier accepted, whose wrongness could not be established.

    A lead, never a finding, and **excluded from scoring**. This is the mechanism that keeps
    an equivalent mutant from becoming a false accusation.
    """

    task_id: str
    candidate: Candidate
    verdict: Verdict
    reason: str


@dataclass(frozen=True, slots=True)
class BaselineFailure:
    """The taskset's own reference solution did not pass its own verifier.

    Mutation testing requires a green baseline: mutants run against a failing suite
    produce noise rather than signal. Here the consequence is sharper than noise — with no
    baseline, "this verifier is weak" cannot be told apart from "the candidates were submitted
    in a form this verifier does not understand", and reporting the first when the second is
    true blames the grader's author for the checker's own defect.

    Such a task is excluded from the acceptance score and recorded separately. It is also
    worth attention in its own right: a reference that fails its own verifier is a real
    defect, just a different one.
    """

    task_id: str
    reward: float
    reason: str


@dataclass(frozen=True, slots=True)
class Flake:
    """A task whose verifier disagreed with itself across repeats of one submission."""

    task_id: str
    rewards: tuple[float, ...]

    @property
    def spread(self) -> float:
        return max(self.rewards) - min(self.rewards)

    @property
    def summary(self) -> str:
        seen = ", ".join(f"{r:g}" for r in self.rewards)
        return f"{self.task_id}: identical submission scored {seen}"


@dataclass(frozen=True, slots=True)
class GroundTruthRejected:
    """The verifier refused every certified rendering of the taskset's own answer.

    The rejection half of the gap. A verifier that rejects correct work trains a model away
    from it — the gradient says the right answer was wrong — which is the same defect as
    accepting wrong work with the sign reversed.

    **What this does and does not establish.** It records a *search budget*: N certified
    meaning-preserving renderings were submitted and none passed. It does not claim the
    verifier is broken, because three different situations produce an identical result:

    * the comparison really is broken, and correct answers are being thrown away;
    * the verifier enforces an **output contract the prompt documents** — a task that wants
      the answer inside tags but stores the bare answer, so refusing the stored value is that
      verifier working correctly;
    * the reward **never reads the reply at all** — it scores a value set elsewhere in the
      episode, so nothing submitted offline can ever pass and nothing was really "refused".

    Only the first is a defect. That is why this record carries a weight of zero and
    contributes nothing to the Verification Gap: a number that pooled all three would report
    correct verifiers as broken.

    ``summary`` is worded to survive being quoted out of context, since a finding that reads
    as an accusation will be repeated as one.
    """

    task_id: str
    #: The declared answer, as stored by the taskset.
    reference: str
    #: Ids of the relations whose renderings were submitted, in the order tried.
    relations_tried: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        n = len(self.relations_tried)
        return f"{self.task_id}: no rendering of the declared answer was accepted ({n} tried)"


@dataclass(frozen=True, slots=True)
class HarnessDisruption:
    """A well-formed submission made the verifier crash, hang, or blow a limit.

    A reward function is a program, and a program that raises on an ordinary string reply is
    broken in a way its author would want to know about. Published work on reward hacking
    treats this as a first-class exploit category — agents avoid unfavourable scoring by
    "triggering timeouts, crashing the harness, exhausting memory or disk" — and scores such
    attempts fail-closed *while still logging them as exploit attempts*.

    **The burden of well-formedness is on the checker.** Every payload is an ordinary program
    or set of file changes, which must never crash a well-written grader, so a crash is the
    verifier's defect. To keep that honest, this is only recorded for a task where **some
    other candidate scored successfully** — that isolates the payload as the trigger. A task
    where every attempt failed is a setup, network or environment problem, and is recorded as
    unmeasurable rather than blamed on the grader.

    Distinct from :class:`Exploit`: nothing was accepted. It is a robustness defect in the
    verifier, not a false positive in its judgement, so it carries no ``Ground`` and does not
    claim one.
    """

    task_id: str
    #: The exception or timeout the reward function raised.
    error: str
    #: The submission that triggered it, so the reader can judge well-formedness.
    payload: Payload
    operator: str = ""

    @property
    def summary(self) -> str:
        return f"{self.task_id}: the verifier failed on a well-formed submission ({self.error[:80]})"


@dataclass(frozen=True, slots=True)
class AnswerInPrompt:
    """A task's declared answer is written, verbatim, in that task's own prompt.

    A task whose answer can be copied does not test whether the answer can be produced, and a
    grader checking only that the answer *appears* in the reply pays full marks for the copy.

    **A lead, never a verdict.** An extractive task — reading comprehension, a look-up — is
    meant to contain its answer, and it produces exactly this record. So it carries a weight
    of zero and ``summary`` states what was found, not what it means. ``compared_with`` is
    the size of the control group: tasks with a provably different answer whose prompts were
    checked and did *not* contain this one.
    """

    task_id: str
    #: The declared answer, as stored by the taskset.
    reference: str
    #: The match with its surrounding context, as written in the prompt.
    excerpt: str
    compared_with: int = 0

    @property
    def summary(self) -> str:
        return f"{self.task_id}: the declared answer appears verbatim in the prompt"


Finding = Exploit | Flake | GroundTruthRejected | HarnessDisruption | AnswerInPrompt

__all__ = [
    "AnswerInPrompt",
    "BaselineFailure",
    "Exploit",
    "Finding",
    "Flake",
    "GroundTruthRejected",
    "HarnessDisruption",
    "Unverified",
]
