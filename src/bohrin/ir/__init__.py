"""Canonical types shared by adapters, probes and the report."""

from __future__ import annotations

from bohrin.ir.evidence import BaselineFailure, Exploit, Finding, Flake, Unverified
from bohrin.ir.task import Candidate, Ground, Provenance, Task, Verdict

__all__ = [
    "BaselineFailure",
    "Candidate",
    "Exploit",
    "Finding",
    "Flake",
    "Ground",
    "Provenance",
    "Task",
    "Unverified",
    "Verdict",
]
