"""The intermediate representation a probe sees.

Probes are written against these types and never against a specific environment format.
That is what makes the adapter layer replaceable and the probe set portable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Ground(StrEnum):
    """How a candidate's incorrectness was established.

    The critical property is that every ground is established **independently of the
    verifier under audit**. A candidate that passes because the verifier is lenient tells
    us nothing about whether the candidate is wrong; that has to be settled separately, or
    Bohrin ends up reporting a correct verifier as broken.
    """

    #: The candidate provably does not do the work: no answer produced, body emptied,
    #: required side effect removed. Wrongness holds by construction.
    STRUCTURAL = "structural"

    #: The candidate differs observably from a known-good reference. Strongest ground,
    #: but requires the taskset to supply a reference.
    DIFFERENTIAL = "differential"

    #: The candidate violates an invariant the taskset itself declares, independently of
    #: the reward function being probed.
    INVARIANT = "invariant"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a candidate came from, so a finding can be reproduced and argued with."""

    operator: str
    #: What the candidate was derived from — "reference", "prompt", or "constant".
    base: str
    #: One line a human can read: what was changed and why that makes it wrong.
    detail: str


@dataclass(frozen=True, slots=True)
class Candidate:
    """A submission Bohrin constructed, carrying a claim about its own correctness."""

    payload: str
    provenance: Provenance

    #: How wrongness was established, or None when it was not. This field is load-bearing:
    #: only a candidate with a ground may ever be reported as an exploit.
    ground: Ground | None = None

    @property
    def known_wrong(self) -> bool:
        """True only when incorrectness was established independently of the verifier."""
        return self.ground is not None


@dataclass(frozen=True, slots=True)
class Task:
    """One unit of work with a verifier attached."""

    id: str
    prompt: str

    #: A known-good solution, when the taskset provides one. Without it, the differential
    #: ground is unavailable and the probe falls back to structural operators only.
    reference: str | None = None

    #: Names of the reward functions this task scores. Length is informative: a single
    #: reward function is the common case in practice.
    reward_fns: tuple[str, ...] = ()

    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the verifier said about a candidate."""

    reward: float
    passed: bool
    per_fn: Mapping[str, float] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["Candidate", "Ground", "Provenance", "Task", "Verdict"]
