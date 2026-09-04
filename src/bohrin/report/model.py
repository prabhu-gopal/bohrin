"""The serialized report — the contract `--json` consumers depend on."""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bohrin.execute.isolation import Assessment, Isolation
from bohrin.ir.evidence import Exploit, Flake
from bohrin.probes.base import ProbeResult, ProbeStatus
from bohrin.scoring.gap import GapScore
from bohrin.version import REPORT_SCHEMA_VERSION, __version__


@dataclass(frozen=True, slots=True)
class Report:
    """One audit."""

    target: str
    adapter: str
    gap: GapScore
    results: tuple[ProbeResult, ...]
    tasks_total: int
    #: How the verifier's code was executed. Part of the evidence: a result produced with
    #: no boundary must never be mistaken for one produced inside a container.
    isolation: Assessment | None = None

    def command_for(self, finding: Exploit | Flake) -> str:
        """The command that re-runs exactly this finding.

        A finding is evidence only if the reader can re-run it, so this must be
        copy-pasteable as printed. The probe emits the selecting flags and knows nothing
        else; the target and `--unsafe-local` are added here, where they are known — and
        `--unsafe-local` is added only when the audit actually ran without a boundary,
        because printing it otherwise would teach the reader to pass it by reflex.
        """
        parts = ["bohrin audit", shlex.quote(self.target), finding.repro_args]
        if self.isolation is not None and self.isolation.effective is Isolation.NONE:
            parts.append("--unsafe-local")
        return " ".join(parts)

    @property
    def findings(self) -> int:
        return sum(len(r.findings) for r in self.results)

    @property
    def unverified(self) -> int:
        return sum(len(r.unverified) for r in self.results)

    def to_dict(self) -> dict[str, Any]:
        """Serialize. The gap and its coverage are emitted together, always."""
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "bohrin_version": __version__,
            "target": self.target,
            "adapter": self.adapter,
            "tasks_total": self.tasks_total,
            "isolation": self.isolation.to_dict() if self.isolation else None,
            "verification_gap": {
                "score": self.gap.score,
                "coverage": {
                    "measured": list(self.gap.coverage.measured),
                    "total": self.gap.coverage.total,
                },
            },
            "probes": [_probe_to_dict(r, self.command_for) for r in self.results],
        }


def _probe_to_dict(result: ProbeResult, command_for: Callable[[Exploit | Flake], str]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": result.probe_id,
        "status": result.status.value,
        "tasks_probed": result.tasks_probed,
        "sub_score": result.sub_score,
        "findings": [_finding_to_dict(f, command_for) for f in result.findings],
        "unverified": [
            {
                "task_id": u.task_id,
                "operator": u.candidate.provenance.operator,
                "payload": u.candidate.payload,
                "reason": u.reason,
            }
            for u in result.unverified
        ],
        "detail": dict(result.detail),
    }
    if result.status is not ProbeStatus.OK:
        out["reason"] = result.reason
    return out


def _finding_to_dict(finding: Exploit | Flake, command_for: Callable[[Exploit | Flake], str]) -> dict[str, Any]:
    if isinstance(finding, Exploit):
        return {
            "kind": "exploit",
            "task_id": finding.task_id,
            "operator": finding.candidate.provenance.operator,
            "ground": finding.candidate.ground.value if finding.candidate.ground else None,
            "detail": finding.candidate.provenance.detail,
            "payload": finding.candidate.payload,
            "reward": finding.verdict.reward,
            "repro": command_for(finding),
        }
    return {
        "kind": "flake",
        "task_id": finding.task_id,
        "rewards": list(finding.rewards),
        "spread": finding.spread,
        "repro": command_for(finding),
    }


__all__ = ["Report"]
