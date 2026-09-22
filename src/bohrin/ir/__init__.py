"""Canonical types: tasks, candidates, verdicts, findings and check results."""

from __future__ import annotations

from bohrin.ir.evidence import BaselineFailure, Exploit, Finding, Flake, Unverified
from bohrin.ir.result import ProbeResult, ProbeStatus
from bohrin.ir.task import Candidate, Ground, Provenance, Task, Verdict

__all__ = [
    "BaselineFailure",
    "Candidate",
    "Exploit",
    "Finding",
    "Flake",
    "Ground",
    "ProbeResult",
    "ProbeStatus",
    "Provenance",
    "Task",
    "Unverified",
    "Verdict",
]
