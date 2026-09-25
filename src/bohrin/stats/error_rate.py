"""The error-rate method: how often a grader-checking tool is wrong, and how much it misses.

A tool that accuses graders has to publish how often it is wrong, in a form anyone can recompute
for any tool. Two measures, from two published line formats:

* **Precision: false accusations per 1,000 proven findings**, per battery, per probe and overall,
  with a Wilson 95% interval (so zero false accusations in 40 findings reads as "at most 88 per
  1,000", not as "never wrong"). A **false accusation** is a finding withdrawn after a successful
  maintainer dispute, or one contradicted by a correct fixture of the conformance suite. A dispute
  still open counts neither way until it is resolved, and is reported. Findings proven by a method
  still marked experimental are reported apart, never in the headline. The **dismissal rate**
  (findings a user dismissed without disputing) is reported beside it per probe: not an error, but
  the "effective false positive" signal Google's analysis platform tracks.
* **Recall on planted weaknesses**, per weakness class: of the known instances in a corpus, how
  many the tool **tried** (submitted a probe for), how many the grader **accepted** (the defect was
  exercised) and how many it **proved** (a finding with a reproduction). This follows Magma's
  reached, triggered and detected (Hazimeh, Herrera and Payer, POMACS 2020), each with its interval.

Nothing here runs a tool or a grader. It reads what a tool reported and what became of it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

from bohrin.evidence import _strict as strict
from bohrin.scoring.interval import wilson_interval
from bohrin.spec.ids import FINDING_ID, PROBE_ID, WEAKNESS_ID, weakness_number

FINDING_OUTCOME_SCHEMA = "https://bohrin.com/schema/finding-outcome/v1"
RECALL_ROW_SCHEMA = "https://bohrin.com/schema/recall-row/v1"
LEVELS = ("proven", "proven-experimental")
OUTCOMES = ("stands", "disputed", "withdrawn-after-dispute", "contradicted-by-fixture")
#: The outcomes that make a finding a false accusation.
FALSE = frozenset({"withdrawn-after-dispute", "contradicted-by-fixture"})
PER = 1000


@dataclass(frozen=True, slots=True)
class Outcome:
    """What became of one reported finding."""

    finding: str
    probe: str
    battery: int
    level: str
    outcome: str
    dismissed: bool


@dataclass(frozen=True, slots=True)
class Planted:
    """What a tool did with one known, planted weakness."""

    weakness: str
    instance: str
    tried: bool
    accepted: bool
    proven: bool
    method: str | None = None


def _choice(value: Any, where: str, choices: Sequence[str]) -> str:
    text = strict.string(value, where)
    if text not in choices:
        raise ValueError(f"{where}: must be one of {list(choices)}")
    return text


def read_outcome(data: Any, line: int = 0) -> Outcome:
    """One finding-outcome line, read strictly."""
    where = f"line {line}"
    fields = frozenset({"finding", "probe", "battery", "level", "outcome", "dismissed"})
    row = strict.obj(data, where, fields, fields)
    return Outcome(
        finding=strict.string(row["finding"], f"{where}: finding", pattern=FINDING_ID),
        probe=strict.string(row["probe"], f"{where}: probe", pattern=PROBE_ID),
        battery=strict.integer(row["battery"], f"{where}: battery", minimum=1),
        level=_choice(row["level"], f"{where}: level", LEVELS),
        outcome=_choice(row["outcome"], f"{where}: outcome", OUTCOMES),
        dismissed=strict.boolean(row["dismissed"], f"{where}: dismissed"),
    )


def read_planted(data: Any, line: int = 0) -> Planted:
    """One recall line, read strictly: proven implies accepted, and accepted implies tried."""
    where = f"line {line}"
    row = strict.obj(
        data,
        where,
        frozenset({"weakness", "instance", "tried", "accepted", "proven", "method"}),
        frozenset({"weakness", "instance", "tried", "accepted", "proven"}),
    )
    planted = Planted(
        weakness=strict.string(row["weakness"], f"{where}: weakness", pattern=WEAKNESS_ID),
        instance=strict.string(row["instance"], f"{where}: instance", empty=False),
        tried=strict.boolean(row["tried"], f"{where}: tried"),
        accepted=strict.boolean(row["accepted"], f"{where}: accepted"),
        proven=strict.boolean(row["proven"], f"{where}: proven"),
        method=strict.string(row["method"], f"{where}: method", empty=False) if "method" in row else None,
    )
    if planted.accepted and not planted.tried:
        raise ValueError(f"{where}: accepted without being tried")
    if planted.proven and not planted.accepted:
        raise ValueError(f"{where}: proven without being accepted")
    return planted


def read_lines(lines: Iterable[str], reader: Any) -> list[Any]:
    """Every row of a JSON Lines file, read with ``reader``. Blank lines are skipped."""
    rows = []
    for number, text in enumerate(lines, start=1):
        if not text.strip():
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {number}: not JSON ({exc.msg})") from exc
        rows.append(reader(data, number))
    return rows


# --------------------------------------------------------------------------- precision


@dataclass(frozen=True, slots=True)
class Precision:
    """False accusations among resolved proven findings, for one group."""

    battery: int
    #: The probe, or None for every probe of the battery.
    probe: str | None
    false: int
    #: Proven findings whose standing is settled: they stand or were overturned.
    resolved: int
    #: Proven findings under an open dispute, counted neither way.
    disputed: int
    dismissed: int
    #: Every proven finding reported, whatever became of it.
    reported: int

    @property
    def per_thousand(self) -> float | None:
        """False accusations per 1,000 resolved proven findings, or None when none is resolved."""
        return PER * self.false / self.resolved if self.resolved else None

    @property
    def interval_per_thousand(self) -> tuple[float, float] | None:
        """The Wilson 95% interval, per 1,000."""
        interval = wilson_interval(self.false, self.resolved)
        return None if interval is None else (PER * interval[0], PER * interval[1])

    @property
    def dismissal_rate(self) -> float | None:
        """The share of reported proven findings a user dismissed."""
        return self.dismissed / self.reported if self.reported else None


def _precision(battery: int, probe: str | None, rows: Sequence[Outcome]) -> Precision:
    disputed = sum(r.outcome == "disputed" for r in rows)
    return Precision(
        battery=battery,
        probe=probe,
        false=sum(r.outcome in FALSE for r in rows),
        resolved=len(rows) - disputed,
        disputed=disputed,
        dismissed=sum(r.dismissed for r in rows),
        reported=len(rows),
    )


def precision(outcomes: Iterable[Outcome], level: str = "proven") -> tuple[Precision, ...]:
    """Per battery: the whole battery first, then each probe in ID order. Only findings of ``level``."""
    rows = [o for o in outcomes if o.level == level]
    out: list[Precision] = []
    for battery in sorted({r.battery for r in rows}):
        in_battery = [r for r in rows if r.battery == battery]
        out.append(_precision(battery, None, in_battery))
        for probe in sorted({r.probe for r in in_battery}):
            out.append(_precision(battery, probe, [r for r in in_battery if r.probe == probe]))
    return tuple(out)


# --------------------------------------------------------------------------- recall


@dataclass(frozen=True, slots=True)
class Recall:
    """What a tool did with the planted instances of one weakness class."""

    weakness: str
    planted: int
    tried: int
    accepted: int
    proven: int

    def interval(self, stage: str) -> tuple[float, float] | None:
        """The Wilson 95% interval on the share of planted instances at ``stage``."""
        return wilson_interval(getattr(self, stage), self.planted)


def recall(rows: Iterable[Planted]) -> tuple[Recall, ...]:
    """Per weakness class, in ID order. Raises ``ValueError`` for an instance listed twice."""
    rows = list(rows)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.weakness, row.instance)
        if key in seen:
            raise ValueError(f"{row.instance!r} is listed twice for {row.weakness}")
        seen.add(key)
    out = []
    for weakness in sorted({r.weakness for r in rows}, key=weakness_number):
        group = [r for r in rows if r.weakness == weakness]
        out.append(
            Recall(
                weakness=weakness,
                planted=len(group),
                tried=sum(r.tried for r in group),
                accepted=sum(r.accepted for r in group),
                proven=sum(r.proven for r in group),
            )
        )
    return tuple(out)


# --------------------------------------------------------------------------- the published formats


@cache
def finding_outcome_schema() -> dict[str, Any]:
    """The JSON Schema published at ``https://bohrin.com/schema/finding-outcome/v1``."""
    loaded: dict[str, Any] = json.loads(files("bohrin.stats").joinpath("finding-outcome.v1.json").read_text("utf-8"))
    return loaded


@cache
def recall_row_schema() -> dict[str, Any]:
    """The JSON Schema published at ``https://bohrin.com/schema/recall-row/v1``."""
    loaded: dict[str, Any] = json.loads(files("bohrin.stats").joinpath("recall-row.v1.json").read_text("utf-8"))
    return loaded


def render(precisions: Sequence[Precision], recalls: Sequence[Recall] = ()) -> str:
    """Both measures as text: every rate with its sample and interval, and what counted neither way."""
    lines = []
    for p in precisions:
        name = f"battery {p.battery}" + (f" · {p.probe}" if p.probe else " · every probe")
        interval = p.interval_per_thousand
        if p.per_thousand is None or interval is None:
            rate = "no resolved finding yet"
        else:
            rate = (
                f"{p.per_thousand:.0f} false accusations per 1,000 (95% CI {interval[0]:.0f}–{interval[1]:.0f}), "
                f"{p.false} of {p.resolved}"
            )
        extra = f"; {p.disputed} under open dispute, counted neither way" if p.disputed else ""
        dismissal = f"; dismissed {p.dismissed} of {p.reported}" if p.reported else ""
        lines.append(f"  {name}: {rate}{extra}{dismissal}")
    for r in recalls:
        stages = []
        for stage in ("tried", "accepted", "proven"):
            count = getattr(r, stage)
            interval = r.interval(stage)
            span = f" ({100 * interval[0]:.0f}–{100 * interval[1]:.0f}%)" if interval else ""
            stages.append(f"{stage} {count}{span}")
        lines.append(f"  {r.weakness}: {r.planted} planted · " + " · ".join(stages))
    return "\n".join(lines)


__all__ = [
    "FALSE",
    "FINDING_OUTCOME_SCHEMA",
    "OUTCOMES",
    "RECALL_ROW_SCHEMA",
    "Outcome",
    "Planted",
    "Precision",
    "Recall",
    "finding_outcome_schema",
    "precision",
    "read_lines",
    "read_outcome",
    "read_planted",
    "recall",
    "recall_row_schema",
    "render",
]
