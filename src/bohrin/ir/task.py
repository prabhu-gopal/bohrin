"""The canonical representation of a task, a candidate and a verdict.

Every definition in Bohrin is written against these types and never against a specific
environment format, which is what keeps the definitions portable across formats.
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


class Shape(StrEnum):
    """How a grader is called, which decides what a probe against it means.

    ``numeric``, ``proof`` and ``query`` are defined so the weakness list is complete; no
    probe targets them yet.
    """

    #: (task, source) -> reward, with tests run in-process or in a subprocess.
    PROGRAM = "program"
    #: A program run on inputs, with a checker comparing its output.
    IO = "io"
    #: A repository plus a patch, judged by a test command.
    WORKSPACE = "workspace"
    #: The agent acts in a container, and a script there writes the reward.
    CONTAINER = "container"
    #: A change in a repository with a claim of success, read from version history.
    HISTORY = "history"
    #: A program whose output is compared within a numeric tolerance.
    NUMERIC = "numeric"
    #: A proof checked by a proof assistant.
    PROOF = "proof"
    #: A database query checked by executing it.
    QUERY = "query"


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
    #: ground is unavailable and only structural operators apply.
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
    #: The reward came out *above* full marks as the rubric declares them. ``passed`` means
    #: "reached full marks", and full marks are read from the rubric's weights, which assume
    #: each reward function returns 0 to 1. A rubric paying past that -- a sum of 0-3
    #: criteria, a mean of 1-5 ratings -- has a scale Bohrin does not know, so on it
    #: ``passed`` says only "scored at least 1", not "scored like a correct reply".
    scale_exceeded: bool = False


__all__ = ["Candidate", "Ground", "Provenance", "Shape", "Task", "Verdict"]
