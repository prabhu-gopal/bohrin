"""The probe contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from bohrin.ir.evidence import Finding, Unverified

if TYPE_CHECKING:
    from bohrin.adapters.base import TaskSource
    from bohrin.config import ScanConfig


class ProbeStatus(StrEnum):
    """Whether a probe produced a measurement.

    This is not cosmetic. Only ``OK`` contributes to the Verification Gap; the other two
    are excluded from both the numerator and the denominator. A probe that could not run
    must never be read as a clean bill of health, which is what scoring it zero would do.
    """

    OK = "ok"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """What one probe found."""

    probe_id: str
    status: ProbeStatus
    tasks_probed: int = 0

    #: Normalised to [0, 1] where 0 is a clean verifier. None unless status is OK.
    sub_score: float | None = None

    findings: tuple[Finding, ...] = ()

    #: Accepted candidates whose wrongness could not be established. Advisory only, and
    #: deliberately excluded from ``sub_score``.
    unverified: tuple[Unverified, ...] = ()

    #: Populated when status is ERROR or NOT_APPLICABLE, so the report can say why.
    reason: str = ""

    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status is ProbeStatus.OK and self.sub_score is None:
            raise ValueError(f"probe {self.probe_id!r} reported OK without a sub_score")
        if self.status is not ProbeStatus.OK and self.sub_score is not None:
            raise ValueError(f"probe {self.probe_id!r} reported {self.status.value} with a sub_score")


class Probe(ABC):
    """One way of catching a verifier being wrong."""

    #: Stable identifier, matching the entry-point name.
    id: str = ""

    #: Grouping for the report: "acceptance", "reliability", ...
    family: str = ""

    #: Relative weight in the Verification Gap. Equal weighting until there is measured
    #: evidence on which probe best predicts real harm — inventing weights would be a
    #: claim we cannot support.
    weight: float = 1.0

    @abstractmethod
    def explain(self) -> str:
        """A paragraph a user can read: what this probe asks and why it matters."""

    @abstractmethod
    async def run(self, source: TaskSource, config: ScanConfig) -> ProbeResult:
        """Probe every task in ``source``."""


__all__ = ["Probe", "ProbeResult", "ProbeStatus"]
