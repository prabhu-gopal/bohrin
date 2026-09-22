"""What one check reports: whether it measured, how much, and what it found."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from bohrin.ir.evidence import Finding, Unverified


class ProbeStatus(StrEnum):
    """Whether a check produced a measurement.

    This is not cosmetic. Only ``OK`` contributes to the Verification Gap; the other two are
    excluded from both the numerator and the denominator. A check that could not run must
    never be read as a clean bill of health, which is what scoring it zero would do.
    """

    OK = "ok"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """What one check found."""

    probe_id: str
    status: ProbeStatus
    tasks_probed: int = 0

    #: Normalised to [0, 1] where 0 is a clean verifier. None unless status is OK.
    sub_score: float | None = None

    findings: tuple[Finding, ...] = ()

    #: Accepted candidates whose wrongness could not be established. Advisory only, and
    #: deliberately excluded from ``sub_score``.
    unverified: tuple[Unverified, ...] = ()

    #: Populated when status is ERROR or NOT_APPLICABLE, so a reader can see why.
    reason: str = ""

    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status is ProbeStatus.OK and self.sub_score is None:
            raise ValueError(f"probe {self.probe_id!r} reported OK without a sub_score")
        if self.status is not ProbeStatus.OK and self.sub_score is not None:
            raise ValueError(f"probe {self.probe_id!r} reported {self.status.value} with a sub_score")


__all__ = ["ProbeResult", "ProbeStatus"]
