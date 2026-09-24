"""Canonical types: tasks, candidates, verdicts, findings and check results."""

from __future__ import annotations

from bohrin.ir.evidence import BaselineFailure, Exploit, Finding, Flake, Unverified
from bohrin.ir.result import ProbeResult, ProbeStatus
from bohrin.ir.task import Candidate, Ground, Payload, Provenance, Shape, Source, Task, Verdict, Workspace

__all__ = [
    "BaselineFailure",
    "Candidate",
    "Exploit",
    "Finding",
    "Flake",
    "Ground",
    "Payload",
    "ProbeResult",
    "ProbeStatus",
    "Provenance",
    "Shape",
    "Source",
    "Task",
    "Unverified",
    "Verdict",
    "Workspace",
]
