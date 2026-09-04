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


Finding = Exploit | Flake

__all__ = ["BaselineFailure", "Exploit", "Finding", "Flake", "Unverified"]
