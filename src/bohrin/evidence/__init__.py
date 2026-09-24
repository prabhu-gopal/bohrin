"""Evidence formats: the finding record and its published schema."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any

from bohrin.evidence.finding import (
    LEVELS,
    SCHEMA,
    DifferentiatingInput,
    DifferentiatingObservation,
    Finding,
    Reproduction,
    Run,
    Scored,
    Submission,
    finding_id,
    normalise_finding_id,
)


@cache
def finding_schema() -> dict[str, Any]:
    """The JSON Schema published at ``https://bohrin.com/schema/finding/v1``."""
    loaded: dict[str, Any] = json.loads(files("bohrin.evidence").joinpath("finding.v1.json").read_text("utf-8"))
    return loaded


__all__ = [
    "LEVELS",
    "SCHEMA",
    "DifferentiatingInput",
    "DifferentiatingObservation",
    "Finding",
    "Reproduction",
    "Run",
    "Scored",
    "Submission",
    "finding_id",
    "finding_schema",
    "normalise_finding_id",
]
