"""Reading a results file: one JSON object per line, one model's score on one task per line.

The format is deliberately small (``https://bohrin.com/schema/results-row/v1``): ``task_id``,
``model`` and ``score`` are required; ``max_score``, ``cluster`` and ``sample`` are optional; any
other field is ignored, so a results file a team already has can usually be read as it is. A
``score`` of ``null`` is a sample that errored and got no score, which is itself worth counting.

A malformed line is refused with its line number rather than skipped: a statistic over a file with
lines silently missing would be the aggregation defect this command exists to catch.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

from bohrin.evidence import _strict as strict

RESULTS_ROW_SCHEMA = "https://bohrin.com/schema/results-row/v1"


@dataclass(frozen=True, slots=True)
class Row:
    """One model's score on one task, for one sample."""

    line: int
    task_id: str
    model: str
    #: None when the sample errored and got no score.
    score: float | None
    max_score: float = 1.0
    cluster: str | None = None
    sample: int | None = None


def read_row(data: Any, line: int = 0) -> Row:
    """One row, read strictly. Raises ``ValueError`` naming the line and the field at fault."""
    where = f"line {line}"
    if not isinstance(data, dict):
        raise ValueError(f"{where}: expected a JSON object")
    missing = sorted({"task_id", "model", "score"} - set(data))
    if missing:
        raise ValueError(f"{where}: missing {missing}")
    score = data["score"]
    max_score = strict.number(data.get("max_score", 1.0), f"{where}: max_score")
    if max_score <= 0:
        raise ValueError(f"{where}: max_score must be above 0")
    return Row(
        line=line,
        task_id=strict.string(data["task_id"], f"{where}: task_id", empty=False),
        model=strict.string(data["model"], f"{where}: model", empty=False),
        score=None if score is None else strict.number(score, f"{where}: score"),
        max_score=max_score,
        cluster=strict.string(data["cluster"], f"{where}: cluster", empty=False) if "cluster" in data else None,
        sample=strict.integer(data["sample"], f"{where}: sample", minimum=0) if "sample" in data else None,
    )


def read_results(lines: Iterable[str]) -> list[Row]:
    """Every row of a JSON Lines results file. Blank lines are skipped; anything else must be a row."""
    rows: list[Row] = []
    for number, text in enumerate(lines, start=1):
        if not text.strip():
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {number}: not JSON ({exc.msg})") from exc
        rows.append(read_row(data, number))
    if not rows:
        raise ValueError("the file has no results")
    return rows


@cache
def results_row_schema() -> dict[str, Any]:
    """The JSON Schema published at ``https://bohrin.com/schema/results-row/v1``."""
    loaded: dict[str, Any] = json.loads(files("bohrin.stats").joinpath("results-row.v1.json").read_text("utf-8"))
    return loaded


__all__ = ["RESULTS_ROW_SCHEMA", "Row", "read_results", "read_row", "results_row_schema"]
