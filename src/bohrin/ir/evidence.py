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
    repro: str

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
class Flake:
    """A task whose verifier disagreed with itself across repeats of one submission."""

    task_id: str
    rewards: tuple[float, ...]
    repro: str

    @property
    def spread(self) -> float:
        return max(self.rewards) - min(self.rewards)

    @property
    def summary(self) -> str:
        seen = ", ".join(f"{r:g}" for r in self.rewards)
        return f"{self.task_id}: identical submission scored {seen}"


Finding = Exploit | Flake

__all__ = ["Exploit", "Finding", "Flake", "Unverified"]
