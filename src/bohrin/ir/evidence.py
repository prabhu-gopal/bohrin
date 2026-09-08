"""Findings: what a probe reports, and what the report renders."""

from __future__ import annotations

from dataclasses import dataclass

from bohrin.ir.task import Candidate, Verdict


@dataclass(frozen=True, slots=True)
class Exploit:
    """A known-wrong candidate that the verifier accepted.

    Constructed only from a candidate whose ``ground`` is set. An accepted candidate whose
    wrongness could not be established is an :class:`Unverified` lead instead — the report
    must never blur the two.
    """

    task_id: str
    candidate: Candidate
    verdict: Verdict
    #: The flags that re-run *just this finding*, without the command or the target — the
    #: probe knows neither. :meth:`Report.command_for` composes the runnable command, so
    #: the target and the isolation flag are added exactly once, where they are known.
    repro_args: str

    @property
    def summary(self) -> str:
        return f"{self.task_id}: accepted {self.candidate.provenance.operator} (reward {self.verdict.reward:g})"


@dataclass(frozen=True, slots=True)
class Unverified:
    """A candidate the verifier accepted, whose wrongness Bohrin could not establish.

    Reported as a lead in a separate advisory section and **excluded from scoring**. This
    is the mechanism that keeps an equivalent mutant from becoming a false accusation.
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
    baseline, Bohrin cannot distinguish "this verifier is weak" from "Bohrin is submitting
    candidates in a form this verifier does not understand", and reporting the first when
    the second is true means blaming a customer for our own integration bug.

    Such a task is excluded from the weak-oracle score and reported separately. It is also
    worth the user's attention in its own right: a reference that fails its own verifier is
    a real defect, just a different one.
    """

    task_id: str
    reward: float
    reason: str


@dataclass(frozen=True, slots=True)
class Flake:
    """A task whose verifier disagreed with itself across repeats of one submission."""

    task_id: str
    rewards: tuple[float, ...]
    #: See :attr:`Exploit.repro_args`.
    repro_args: str

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

    The rejection half of the gap. A verifier that rejects correct work trains a model
    away from it — the gradient says the right answer was wrong — which is the same defect
    as accepting wrong work with the sign reversed.

    **What this does and does not establish.** It reports a *search budget*: N certified
    meaning-preserving renderings were submitted and none passed. It does not claim the
    verifier is broken, because three different situations produce an identical result and
    Bohrin cannot yet tell them apart:

    * the comparison really is broken, and correct answers are being thrown away;
    * the verifier enforces an **output contract the prompt documents** — ``reverse_text``
      wants the answer inside ``<reversed_text>`` tags and stores the bare reversal, so
      refusing the stored value is that verifier working correctly;
    * the reward **never reads the reply at all** — ``code_golf`` scores
      ``trace.metrics.get("passed")``, a value set elsewhere in the episode, so nothing
      submitted offline can ever pass and nothing was really "refused".

    Only the first is a defect. That is why the probe emitting this carries a weight of
    zero and contributes nothing to the Verification Gap: a number that pooled all three
    would report correct verifiers as broken.

    ``summary`` is worded to survive being quoted out of context, since a finding that
    reads as an accusation will be repeated as one.
    """

    task_id: str
    #: The declared answer, as stored by the taskset.
    reference: str
    #: Ids of the relations whose renderings were submitted, in the order tried.
    relations_tried: tuple[str, ...] = ()
    repro_args: str = ""

    @property
    def summary(self) -> str:
        n = len(self.relations_tried)
        return f"{self.task_id}: no rendering of the declared answer was accepted ({n} tried)"


@dataclass(frozen=True, slots=True)
class HarnessDisruption:
    """A well-formed submission made the verifier crash, hang, or blow a limit.

    A reward function is a program, and a program that raises on an ordinary string reply
    is broken in a way its author would want to know about. Published work on reward
    hacking treats this as a first-class exploit category — agents avoid unfavourable
    scoring by "triggering timeouts, crashing the harness, exhausting memory or disk" — and
    scores such attempts fail-closed *while still logging them as exploit attempts*. Bohrin
    did the fail-closed half and dropped the logging half, counting the crash as noise.

    **The burden of well-formedness is ours.** Every payload Bohrin submits is a plain
    string; an ordinary string must never crash a well-written reward function, so a crash
    is the verifier's defect and not ours. To keep that honest, this is only reported for a
    task where **some other candidate scored successfully** — that isolates the payload as
    the trigger. A task where every attempt failed is a setup, network or environment
    problem, and is reported as an unmeasurable task rather than blamed on the grader.

    Distinct from :class:`Exploit`: nothing was accepted. It is a robustness defect in the
    verifier, not a false positive in its judgement, so it carries no ``Ground`` and does
    not claim one.
    """

    task_id: str
    #: The exception or timeout, as reported by the runner.
    error: str
    #: The submission that triggered it, so the reader can judge well-formedness.
    payload: str
    operator: str = ""
    repro_args: str = ""

    @property
    def summary(self) -> str:
        return f"{self.task_id}: the verifier failed on a well-formed submission ({self.error[:80]})"


Finding = Exploit | Flake | GroundTruthRejected | HarnessDisruption

__all__ = ["BaselineFailure", "Exploit", "Finding", "Flake", "GroundTruthRejected", "HarnessDisruption", "Unverified"]
