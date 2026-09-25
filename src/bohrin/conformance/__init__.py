"""The conformance suite: fixture graders with known defects, and the check of a tool's results.

Modelled on test262 and the JSON Schema Test Suite (open cases as data, usable by any runner) and
on the paired good and bad cases of NIST's Juliet suite. Each weakness of a level has a pair of
graders in ``conformance/<level>/`` of the repository: one correct, one with exactly that defect.
A checking tool runs its checks on every grader and writes what it flagged; :func:`check` compares
that with the expected results in ``bcl-1.toml``.

A tool **achieves a level** when, over every weakness of the level that has fixtures:

* it flags each grader with a defect, with that defect's ID (**detected**);
* it flags nothing on each correct grader (**clean**): a false accusation fails the level, however
  many defects were found;
* it flags no other weakness on a grader with a defect (a **misattribution** is an accusation of
  something that is not there).

A fixture that errored, was skipped or is missing from the results is neither detected nor clean,
so it fails the level too.

Beside the level it reports the tool's true-positive rate over graders with a defect, its
false-positive rate over correct graders, and their difference, Youden's index, as the OWASP
Benchmark scores security tools; the level itself never trades one for the other.

The check runs no grader. It reads two files and compares them.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

from bohrin.evidence import _strict as strict
from bohrin.ir.task import Shape
from bohrin.spec.ids import CONFORMANCE_LEVEL, WEAKNESS_ID
from bohrin.spec.weaknesses import weakness_list

CONFORMANCE_RESULTS_SCHEMA = "https://bohrin.com/schema/conformance-results/v1"
STATUSES = ("ran", "error", "skipped")
#: A fixture ID: ``<level>/<weakness slug>/correct`` or ``.../defect``.
FIXTURE_ID = re.compile(r"bcl-[1-4]/[a-z0-9]+(?:-[a-z0-9]+)*/(?:correct|defect)")


@dataclass(frozen=True, slots=True)
class Fixture:
    """One fixture grader and the result a tool must get on it."""

    id: str
    #: The grader's file name in ``conformance/<level>/`` of the repository.
    file: str
    weakness: str
    shape: Shape
    #: Whether this grader has the weakness (True) or is its correct counterpart (False).
    defect: bool


@dataclass(frozen=True, slots=True)
class Suite:
    """A conformance level's fixtures."""

    level: str
    version: int
    shapes: tuple[Shape, ...]
    #: Every weakness the level covers.
    weaknesses: tuple[str, ...]
    #: Weaknesses of the level with no fixture yet.
    pending: tuple[str, ...]
    fixtures: tuple[Fixture, ...]

    @property
    def covered(self) -> tuple[str, ...]:
        """The weaknesses the level is checked over: those with fixtures."""
        return tuple(w for w in self.weaknesses if w not in self.pending)


def _suite(data: Mapping[str, Any]) -> Suite:
    head = strict.obj(data.get("suite"), "suite", frozenset({"level", "version", "shapes", "weaknesses", "pending"}))
    level = strict.string(head["level"], "suite.level", pattern=CONFORMANCE_LEVEL)
    weaknesses = strict.array(
        head["weaknesses"], "suite.weaknesses", lambda v, w: strict.string(v, w, pattern=WEAKNESS_ID)
    )
    pending = strict.array(head["pending"], "suite.pending", lambda v, w: strict.string(v, w, pattern=WEAKNESS_ID))
    fixtures = []
    for index, raw in enumerate(data.get("fixture", [])):
        where = f"fixture[{index}]"
        entry = strict.obj(raw, where, frozenset({"id", "file", "weakness", "shape", "defect"}))
        fixtures.append(
            Fixture(
                id=strict.string(entry["id"], f"{where}.id", pattern=FIXTURE_ID),
                file=strict.string(entry["file"], f"{where}.file", empty=False),
                weakness=strict.string(entry["weakness"], f"{where}.weakness", pattern=WEAKNESS_ID),
                shape=Shape(strict.string(entry["shape"], f"{where}.shape")),
                defect=strict.boolean(entry["defect"], f"{where}.defect"),
            )
        )
    return Suite(
        level=level,
        version=strict.integer(head["version"], "suite.version", minimum=1),
        shapes=tuple(Shape(s) for s in strict.array(head["shapes"], "suite.shapes", strict.string)),
        weaknesses=weaknesses,
        pending=pending,
        fixtures=tuple(fixtures),
    )


@cache
def suite(level: str = "BCL-1") -> Suite:
    """The published suite for ``level``. Only BCL-1 exists so far."""
    if level != "BCL-1":
        raise KeyError(f"no conformance suite for {level} yet; BCL-1 is the first")
    return _suite(tomllib.loads(files("bohrin.conformance").joinpath("bcl-1.toml").read_text("utf-8")))


@cache
def conformance_results_schema() -> dict[str, Any]:
    """The JSON Schema published at ``https://bohrin.com/schema/conformance-results/v1``."""
    text = files("bohrin.conformance").joinpath("conformance-results.v1.json").read_text("utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


# --------------------------------------------------------------------------- a tool's results


@dataclass(frozen=True, slots=True)
class Result:
    """What a tool reported for one fixture."""

    fixture: str
    status: str
    flagged: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True, slots=True)
class Results:
    """A tool's results for one suite."""

    level: str
    version: int
    tool: str
    tool_version: str
    results: tuple[Result, ...]


def _result(value: Any, where: str) -> Result:
    entry = strict.obj(
        value, where, frozenset({"fixture", "status", "flagged", "message"}), frozenset({"fixture", "status"})
    )
    status = strict.string(entry["status"], f"{where}.status")
    if status not in STATUSES:
        raise ValueError(f"{where}.status: must be one of {list(STATUSES)}")
    if (status == "ran") != ("flagged" in entry):
        raise ValueError(f"{where}: flagged is required when status is ran, and only then")
    flagged = strict.array(
        entry.get("flagged", []), f"{where}.flagged", lambda v, w: strict.string(v, w, pattern=WEAKNESS_ID)
    )
    if len(set(flagged)) != len(flagged):
        raise ValueError(f"{where}.flagged: lists a weakness twice")
    return Result(
        fixture=strict.string(entry["fixture"], f"{where}.fixture", pattern=FIXTURE_ID),
        status=status,
        flagged=flagged,
        message=strict.string(entry["message"], f"{where}.message", empty=False) if "message" in entry else "",
    )


def read_results(data: Any) -> Results:
    """A results document, read strictly: exactly what the published schema allows, or ``ValueError``."""
    top = strict.obj(
        data,
        "results file",
        frozenset({"$schema", "suite", "tool", "results"}),
        frozenset({"$schema", "suite", "tool", "results"}),
    )
    if top["$schema"] != CONFORMANCE_RESULTS_SCHEMA:
        raise ValueError(f"$schema: expected {CONFORMANCE_RESULTS_SCHEMA}")
    head = strict.obj(top["suite"], "suite", frozenset({"level", "version"}), frozenset({"level", "version"}))
    tool = strict.obj(top["tool"], "tool", frozenset({"name", "version"}), frozenset({"name", "version"}))
    return Results(
        level=strict.string(head["level"], "suite.level", pattern=CONFORMANCE_LEVEL),
        version=strict.integer(head["version"], "suite.version", minimum=1),
        tool=strict.string(tool["name"], "tool.name", empty=False),
        tool_version=strict.string(tool["version"], "tool.version", empty=False),
        results=strict.array(top["results"], "results", _result),
    )


# --------------------------------------------------------------------------- the check


@dataclass(frozen=True, slots=True)
class WeaknessOutcome:
    """How a tool did on one weakness's pair of fixtures."""

    weakness: str
    #: It flagged the grader with the defect, with this weakness.
    detected: bool
    #: It flagged nothing on the correct grader.
    clean: bool
    #: Other weaknesses it flagged on the grader with this defect.
    misattributed: tuple[str, ...]
    #: Fixtures of this weakness that did not run (errored, skipped or missing from the results).
    not_run: tuple[str, ...]

    @property
    def passed(self) -> bool:
        """Detected, clean and nothing misattributed. A fixture that did not run is neither detected nor
        clean, so it fails here without a rule of its own; ``not_run`` says why."""
        return self.detected and self.clean and not self.misattributed


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    """The result of checking a tool's results against a suite."""

    suite: Suite
    tool: str
    tool_version: str
    outcomes: tuple[WeaknessOutcome, ...]
    #: Graders with a defect that were flagged with it, of all graders with a defect.
    true_positives: int
    defective: int
    #: Correct graders that were flagged with anything, of all correct graders.
    false_positives: int
    correct: int

    @property
    def achieved(self) -> bool:
        """Whether the tool achieves the level, over the weaknesses that have fixtures."""
        return all(outcome.passed for outcome in self.outcomes)

    @property
    def youden(self) -> float:
        """True-positive rate minus false-positive rate, from -1 to 1."""
        tpr = self.true_positives / self.defective if self.defective else 0.0
        fpr = self.false_positives / self.correct if self.correct else 0.0
        return tpr - fpr

    def to_json(self) -> dict[str, Any]:
        """The report as a plain JSON object."""
        return {
            "level": self.suite.level,
            "suite_version": self.suite.version,
            "tool": {"name": self.tool, "version": self.tool_version},
            "achieved": self.achieved,
            "weaknesses_checked": list(self.suite.covered),
            "weaknesses_pending": list(self.suite.pending),
            "true_positives": self.true_positives,
            "defective": self.defective,
            "false_positives": self.false_positives,
            "correct": self.correct,
            "outcomes": [
                {
                    "weakness": o.weakness,
                    "detected": o.detected,
                    "clean": o.clean,
                    "misattributed": list(o.misattributed),
                    "not_run": list(o.not_run),
                    "passed": o.passed,
                }
                for o in self.outcomes
            ],
        }


def check(results: Results) -> ConformanceReport:
    """Compare a tool's results with the suite they name.

    Raises ``ValueError`` when the results are for another suite or version, name a fixture the
    suite does not have, or report one fixture twice: such a file cannot be checked, only refused.
    """
    try:
        expected = suite(results.level)
    except KeyError as exc:
        raise ValueError(str(exc.args[0])) from exc
    if results.version != expected.version:
        raise ValueError(
            f"the results are for {results.level} version {results.version}; this is version {expected.version}"
        )
    by_id = {fixture.id: fixture for fixture in expected.fixtures}
    reported: dict[str, Result] = {}
    for result in results.results:
        if result.fixture not in by_id:
            raise ValueError(f"{result.fixture!r} is not a fixture of {expected.level} version {expected.version}")
        if result.fixture in reported:
            raise ValueError(f"{result.fixture!r} is reported twice")
        reported[result.fixture] = result

    outcomes = []
    true_positives = false_positives = 0
    for weakness in expected.covered:
        pair = [f for f in expected.fixtures if f.weakness == weakness]
        not_run = tuple(f.id for f in pair if f.id not in reported or reported[f.id].status != "ran")
        detected = clean = True
        misattributed: tuple[str, ...] = ()
        for fixture in pair:
            got = reported.get(fixture.id)
            flagged = set(got.flagged) if got is not None and got.status == "ran" else None
            if fixture.defect:
                detected = flagged is not None and weakness in flagged
                misattributed = tuple(sorted((flagged or set()) - {weakness}))
                true_positives += detected
            else:
                clean = flagged is not None and not flagged
                false_positives += bool(flagged)
        outcomes.append(WeaknessOutcome(weakness, detected, clean, misattributed, not_run))
    return ConformanceReport(
        suite=expected,
        tool=results.tool,
        tool_version=results.tool_version,
        outcomes=tuple(outcomes),
        true_positives=true_positives,
        defective=sum(1 for f in expected.fixtures if f.defect and f.weakness in expected.covered),
        false_positives=false_positives,
        correct=sum(1 for f in expected.fixtures if not f.defect and f.weakness in expected.covered),
    )


def render(report: ConformanceReport, source: str = "") -> str:
    """The report as text, in the four parts every Bohrin command uses."""
    s = report.suite
    names = {w.id: w.name for w in weakness_list().weaknesses}
    lines = [
        f"bohrin conformance check · {source or 'results'} · {report.tool} {report.tool_version} · "
        f"{s.level} version {s.version} · {len(s.fixtures)} fixtures",
        "",
    ]
    missed = sum(not o.detected for o in report.outcomes)
    accused = sum(not o.clean for o in report.outcomes) + sum(bool(o.misattributed) for o in report.outcomes)
    if report.achieved:
        lines.append(f"  {s.level} achieved: every defect was flagged, and no correct grader was.")
    else:
        lines.append(
            f"  {s.level} not achieved: {missed} defect{'' if missed == 1 else 's'} missed, "
            f"{accused} false accusation{'' if accused == 1 else 's'}."
        )
    lines.append(
        f"  Score {100 * report.youden:.0f}: {report.true_positives} of {report.defective} defects flagged, "
        f"{report.false_positives} of {report.correct} correct graders flagged."
    )
    lines.append("")
    for o in report.outcomes:
        state = "passed" if o.passed else "FAILED"
        detail = []
        if not o.detected:
            detail.append("defect not flagged")
        if not o.clean:
            detail.append("correct grader flagged")
        if o.misattributed:
            detail.append(f"also flagged {', '.join(o.misattributed)}")
        if o.not_run:
            detail.append(f"did not run: {', '.join(o.not_run)}")
        lines.append(f"  {o.weakness:<8} {names.get(o.weakness, ''):<30} {state}   {'; '.join(detail)}".rstrip())
    lines.append("")
    if s.pending:
        lines.append(
            f"  Not in this suite yet: {', '.join(s.pending)}. The level is checked over "
            f"{len(s.covered)} of its {len(s.weaknesses)} weaknesses."
        )
    lines.append('  Next: the fixtures and their contract are in conformance/ and docs/SPEC.md ("Conformance").')
    return "\n".join(lines)


__all__ = [
    "CONFORMANCE_RESULTS_SCHEMA",
    "ConformanceReport",
    "Fixture",
    "Result",
    "Results",
    "Suite",
    "WeaknessOutcome",
    "check",
    "conformance_results_schema",
    "read_results",
    "render",
    "suite",
]
