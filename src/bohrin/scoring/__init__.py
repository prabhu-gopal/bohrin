"""Scoring: the Coverage Score, correct-work acceptance beside it, the Verification Gap, and the
uncertainty of every rate."""

from __future__ import annotations

from bohrin.scoring.coverage import CoverageScore, coverage_score
from bohrin.scoring.gap import Coverage, GapScore, verification_gap
from bohrin.scoring.interval import rate, wilson_interval
from bohrin.scoring.scorecard import Acceptance, ControlAttempt, Scorecard, correct_work_acceptance

__all__ = [
    "Acceptance",
    "ControlAttempt",
    "Coverage",
    "CoverageScore",
    "GapScore",
    "Scorecard",
    "correct_work_acceptance",
    "coverage_score",
    "rate",
    "verification_gap",
    "wilson_interval",
]
