"""``bohrin power``: is an evaluation big enough to support what it is used to claim?

From a results file a team already has, it reports each model's score with an interval suited to
the sample, the smallest difference the evaluation can detect, whether the models it compares are
actually distinguishable, and an audit of how the scores were aggregated:

* samples that errored and are silently left out of a denominator (BGW-128);
* rewards outside ``0 .. max_score`` (BGW-128);
* tasks one model has a result for and another does not (BGW-128);
* the same sample reported twice (BGW-128);
* partial-credit scores, which can reward a wrong approach (BGW-122);
* an evaluation too small to detect the difference its user cares about (BGW-133), judged only
  against a difference the user states, never against an invented threshold.

Errored samples count as failures in the headline score, because a harness that errors has not
shown the model succeeded; the score with them dropped is shown beside it. Everything reported is
a fact about the file or a statistic, never an accusation.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files
from typing import Any

from bohrin.scoring.interval import wilson_interval
from bohrin.stats.estimates import (
    FEW_HUNDRED,
    detectable_difference,
    mean,
    normal_interval,
    standard_error,
)
from bohrin.stats.results import Row

POWER_REPORT_SCHEMA = "https://bohrin.com/schema/power-report/v1"


@dataclass(frozen=True, slots=True)
class Observation:
    """A fact the audit found, tied to the weakness class it is evidence of."""

    weakness: str
    message: str
    model: str | None = None


@dataclass(frozen=True, slots=True)
class ModelScore:
    """One model's score over the tasks it was run on."""

    model: str
    tasks: int
    samples: int
    errored: int
    score: float
    #: The score with errored samples left out of the denominator, as some harnesses report it.
    score_errors_dropped: float | None
    interval: tuple[float, float] | None
    method: str
    standard_error: float
    #: The smallest difference from an independent model of similar spread found with 80% power.
    detectable: float | None


@dataclass(frozen=True, slots=True)
class Comparison:
    """Two models on the tasks both were run on, compared task by task (paired)."""

    first: str
    second: str
    tasks: int
    difference: float
    interval: tuple[float, float] | None
    detectable: float | None

    @property
    def distinguishable(self) -> bool:
        """Whether the whole 95% interval of the difference lies on one side of zero."""
        return self.interval is not None and (self.interval[0] > 0 or self.interval[1] < 0)


@dataclass(frozen=True, slots=True)
class PowerReport:
    """Everything ``bohrin power`` says about one results file."""

    source: str
    tasks: int
    clusters: int
    models: tuple[ModelScore, ...]
    comparisons: tuple[Comparison, ...]
    findings: tuple[Observation, ...]
    notes: tuple[str, ...] = field(default=())

    def to_json(self) -> dict[str, Any]:
        """The report as ``https://bohrin.com/schema/power-report/v1``."""

        def number(value: float | None) -> float | None:
            """A value for JSON: rounded, and null when it could not be computed."""
            return None if value is None or math.isnan(value) else round(value, 6)

        def interval(value: tuple[float, float] | None) -> list[float] | None:
            """An interval for JSON: two rounded bounds, or null."""
            return None if value is None else [round(value[0], 6), round(value[1], 6)]

        return {
            "$schema": POWER_REPORT_SCHEMA,
            "source": self.source,
            "tasks": self.tasks,
            "clusters": self.clusters,
            "models": [
                {
                    "model": m.model,
                    "tasks": m.tasks,
                    "samples": m.samples,
                    "errored": m.errored,
                    "score": number(m.score),
                    "score_errors_dropped": number(m.score_errors_dropped),
                    "interval_95": interval(m.interval),
                    "method": m.method,
                    "min_detectable_difference": number(m.detectable),
                }
                for m in self.models
            ],
            "comparisons": [
                {
                    "first": c.first,
                    "second": c.second,
                    "tasks": c.tasks,
                    "difference": number(c.difference),
                    "interval_95": interval(c.interval),
                    "min_detectable_difference": number(c.detectable),
                    "distinguishable": c.distinguishable,
                }
                for c in self.comparisons
            ],
            "findings": [
                {"weakness": f.weakness, "message": f.message, **({"model": f.model} if f.model else {})}
                for f in self.findings
            ],
            "notes": list(self.notes),
        }


@cache
def power_report_schema() -> dict[str, Any]:
    """The JSON Schema published at ``https://bohrin.com/schema/power-report/v1``."""
    loaded: dict[str, Any] = json.loads(files("bohrin.stats").joinpath("power-report.v1.json").read_text("utf-8"))
    return loaded


def _finite(value: float) -> float | None:
    return None if math.isnan(value) else value


def analyse(rows: list[Row], source: str = "", min_difference: float | None = None) -> PowerReport:
    """The power report for ``rows``. ``min_difference`` is the difference, on a 0-1 scale, the
    user needs the evaluation to be able to detect; without it, size is reported but not judged."""
    findings: list[Observation] = []
    notes: list[str] = []

    seen: dict[tuple[str, str, int | None], int] = {}
    for row in rows:
        key = (row.model, row.task_id, row.sample)
        if key in seen:
            findings.append(
                Observation(
                    "BGW-128",
                    f"task {row.task_id!r} is reported twice for the same sample (lines {seen[key]} and {row.line}), "
                    "so which score counts is ambiguous.",
                    row.model,
                )
            )
        seen.setdefault(key, row.line)

    cluster_of: dict[str, str] = {}
    for row in rows:
        if row.cluster is not None:
            cluster_of.setdefault(row.task_id, row.cluster)
    clustered = bool(cluster_of)

    models = sorted({row.model for row in rows})
    all_tasks = sorted({row.task_id for row in rows})
    per_model: dict[str, dict[str, list[float]]] = {}
    scores: list[ModelScore] = []
    for model in models:
        mine = [row for row in rows if row.model == model]
        errored = [row for row in mine if row.score is None]
        outside = [row for row in mine if row.score is not None and not 0 <= row.score <= row.max_score]
        partial = [row for row in mine if row.score is not None and 0 < row.score < row.max_score]
        if outside:
            findings.append(
                Observation(
                    "BGW-128",
                    f"{len(outside)} score(s) fall outside 0 to full marks (first on line {outside[0].line}); "
                    "an average over them overstates or understates performance.",
                    model,
                )
            )
        if partial:
            findings.append(
                Observation(
                    "BGW-122",
                    f"{len(partial)} of {len(mine)} scores are partial credit; a reward for the share of tests passed "
                    "can pay most for a fundamentally wrong approach.",
                    model,
                )
            )
        missing = [task for task in all_tasks if task not in {row.task_id for row in mine}]
        if missing:
            findings.append(
                Observation(
                    "BGW-128",
                    f"no result for {len(missing)} task(s) other models were run on (for example {missing[0]!r}); "
                    "comparisons use only tasks every model has.",
                    model,
                )
            )

        failed_closed: dict[str, list[float]] = {}
        errors_dropped: dict[str, list[float]] = {}
        for row in mine:
            value = 0.0 if row.score is None else row.score / row.max_score
            failed_closed.setdefault(row.task_id, []).append(value)
            if row.score is not None:
                errors_dropped.setdefault(row.task_id, []).append(row.score / row.max_score)
        task_scores = {task: mean(values) for task, values in failed_closed.items()}
        per_model[model] = {task: [score] for task, score in task_scores.items()}
        values = [task_scores[task] for task in sorted(task_scores)]
        labels = [cluster_of.get(task, task) for task in sorted(task_scores)] if clustered else None
        centre = mean(values)
        dropped_values = [mean(v) for v in errors_dropped.values() if v]
        dropped = mean(dropped_values) if dropped_values else None
        if errored:
            shown = f"{100 * dropped:.1f}" if dropped is not None else "undefined"
            findings.append(
                Observation(
                    "BGW-128",
                    f"{len(errored)} of {len(mine)} samples errored and have no score; counted as failures the score "
                    f"is {100 * centre:.1f}, and left out of the denominator it would be {shown}.",
                    model,
                )
            )

        error = standard_error(values, labels)
        binary = all(value in (0.0, 1.0) for value in values)
        if binary and not clustered:
            passed = int(sum(values))
            interval = wilson_interval(passed, len(values))
            method = "Wilson score interval"
        else:
            interval = normal_interval(centre, error) if not math.isnan(error) else None
            method = "normal approximation" + (", clustered standard error" if clustered else "")
            if len(values) < FEW_HUNDRED:
                notes.append(
                    f"{model}: a normal-approximation interval over {len(values)} tasks (fewer than a few hundred) "
                    "is likely too narrow."
                )
        detectable = detectable_difference(math.sqrt(2) * error) if not math.isnan(error) else None
        scores.append(
            ModelScore(
                model=model,
                tasks=len(values),
                samples=len(mine),
                errored=len(errored),
                score=centre,
                score_errors_dropped=dropped if errored else None,
                interval=interval,
                method=method,
                standard_error=error,
                detectable=detectable,
            )
        )
        if len(models) == 1 and min_difference is not None and detectable is not None and detectable > min_difference:
            findings.append(
                Observation(
                    "BGW-133",
                    f"with {len(values)} tasks the evaluation detects a difference of {100 * detectable:.1f} points "
                    f"with 80% power, larger than the {100 * min_difference:.1f} you need.",
                    model,
                )
            )

    comparisons: list[Comparison] = []
    for first, second in itertools.combinations(models, 2):
        shared = sorted(set(per_model[first]) & set(per_model[second]))
        differences = [per_model[first][task][0] - per_model[second][task][0] for task in shared]
        if not differences:
            notes.append(f"{first} and {second} share no tasks, so they were not compared.")
            continue
        labels = [cluster_of.get(task, task) for task in shared] if clustered else None
        error = standard_error(differences, labels)
        if math.isnan(error):
            notes.append(f"{first} and {second} share only {len(shared)} task, too few to compare.")
        centre = mean(differences)
        paired = _finite(detectable_difference(error))
        if min_difference is not None and paired is not None and paired > min_difference:
            findings.append(
                Observation(
                    "BGW-133",
                    f"comparing {first} with {second} over {len(shared)} shared tasks, the evaluation detects a "
                    f"difference of {100 * paired:.1f} points with 80% power, larger than the "
                    f"{100 * min_difference:.1f} you need.",
                )
            )
        comparisons.append(
            Comparison(
                first=first,
                second=second,
                tasks=len(shared),
                difference=centre,
                interval=normal_interval(centre, error) if not math.isnan(error) else None,
                detectable=paired,
            )
        )

    return PowerReport(
        source=source,
        tasks=len(all_tasks),
        clusters=len(set(cluster_of.values())),
        models=tuple(scores),
        comparisons=tuple(comparisons),
        findings=tuple(findings),
        notes=tuple(notes),
    )


def _verdict(detectable: float | None, lead: str) -> str:
    """The one-sentence verdict; a detectable difference of the whole scale or more detects nothing."""
    if detectable is None:
        return "  The evaluation is too small to estimate what difference it can detect."
    if detectable >= 1:
        return "  The evaluation is too small to detect any difference: even 0 against 100 would not be found reliably."
    return f"  {lead} {100 * detectable:.1f} points (80% power)."


def render(report: PowerReport) -> str:
    """The report as text, in the four parts every Bohrin command uses."""
    lines = [
        f"bohrin power · {report.source or 'results'} · {len(report.models)} model(s) · {report.tasks} tasks"
        + (f" · {report.clusters} clusters" if report.clusters else ""),
        "",
    ]
    if report.comparisons:
        detectable = max((c.detectable for c in report.comparisons if c.detectable is not None), default=None)
        verdict = _verdict(detectable, "Between these models the evaluation detects a difference of")
    else:
        detectable = max((m.detectable for m in report.models if m.detectable is not None), default=None)
        verdict = _verdict(detectable, "The evaluation detects a difference of about")
    lines += [verdict, ""]
    for m in report.models:
        span = f"95% CI {100 * m.interval[0]:.1f}–{100 * m.interval[1]:.1f}" if m.interval else "no interval"
        lines.append(f"  {m.model:<24} {100 * m.score:5.1f}   {span}   {m.tasks} tasks   ({m.method})")
    for c in report.comparisons:
        if c.interval is None:
            continue
        verdict = "distinguishable" if c.distinguishable else "not distinguishable at this size"
        lines.append(
            f"  {c.first} − {c.second}: {100 * c.difference:+.1f} points "
            f"(95% CI {100 * c.interval[0]:+.1f} to {100 * c.interval[1]:+.1f}, paired over {c.tasks} tasks): {verdict}"
        )
    lines.append("")
    if report.findings:
        lines.append(f"  {len(report.findings)} thing(s) to look at:")
        for f in report.findings:
            who = f"{f.model}: " if f.model else ""
            lines.append(f"  {f.weakness}  {who}{f.message}")
        lines.append("")
    if report.notes:
        lines += [f"  Note: {note}" for note in report.notes]
        lines.append("")
    lines.append("  Next: bohrin power FILE --min-difference 0.02   (judge the size against the difference you need)")
    return "\n".join(lines)


__all__ = [
    "POWER_REPORT_SCHEMA",
    "Comparison",
    "ModelScore",
    "Observation",
    "PowerReport",
    "analyse",
    "power_report_schema",
    "render",
]
