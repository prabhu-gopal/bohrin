"""The scorecard: the Coverage Score and correct-work acceptance, per grader shape, then overall.

A grader that rejects everything catches every cheat, so the Coverage Score alone can be won by
refusing to pay for anything. **Correct-work acceptance** is the other half: of the correct
rewritings of a task's reference (:mod:`bohrin.relations`), what share did the grader accept? A
grader tightened against cheating is exactly the kind that starts rejecting correct code: in one
hacker-fixer loop, two over-restrictive defences dragged a model's pass rate on correct code to
22% (arXiv:2606.08960). The two numbers are printed side by side and **never merged**, because
any single number made from them can be raised by trading one for the other.

**Which tasks can be scored at all.** A rate over a task is only sound if the grader is measuring
the task, so three things take a task, or one attempt, out of every rate (never silently: each
excluded task is listed with its reason):

* **The reference fails its own grader** (invariant I4). If the grader rejects the task's own
  reference, the task is broken or the grader is, and nothing it did on that task means what it
  seems to: rejecting a hollow program is not "catching" it. The task leaves *both* numbers.
* **The grader paid past full marks** (invariant I5). Full marks are then not known, so neither
  "accepted" nor "rejected" can be read. The task leaves both numbers.
* **An attempt could not run** (invariant I6): ``accepted=None``. It is left out of both sides of
  every rate, never counted as rejected, which would score a crash as a catch.

**The baseline is a gate, not a point.** The unchanged reference decides whether a task is scored;
it is not itself counted in acceptance, where every scored task would contribute a free success.
Acceptance on a task is measured only when its baseline was run and accepted: a rewriting the
grader rejects says nothing about the grader if the reference itself was never shown to pass.

**Per shape, then overall.** A grader's defects depend on how it is called, so every shape gets
its own pair of numbers, and each names the weakness classes that apply to the shape but that
nothing in this run measured. A score is not a safety claim: it says what was tried.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from bohrin.ir.task import Shape, Task
from bohrin.mutate import discover
from bohrin.mutate.base import MutationOperator
from bohrin.relations import Control
from bohrin.scoring.coverage import CATEGORIES, Attempt, CoverageScore, coverage_score
from bohrin.scoring.interval import wilson_interval
from bohrin.spec.ids import weakness_number
from bohrin.spec.probes import probe_for
from bohrin.spec.weaknesses import weakness_list

#: Why a task was left out of every rate, in the words the report prints.
BASELINE_REJECTED = "the reference fails its own grader"
PAST_FULL_MARKS = "the grader paid past full marks, so full marks are not known"


@dataclass(frozen=True, slots=True)
class ControlAttempt:
    """One positive control offered to the grader, and what the grader did with it."""

    task_id: str
    control: Control
    #: Whether the grader paid full marks; None when the attempt could not run.
    accepted: bool | None
    #: The grader paid more than full marks, so its scale is not the one assumed.
    scale_exceeded: bool = False


@dataclass(frozen=True, slots=True)
class RelationResult:
    """How the rewritings of one relation fared across the tasks they were tried on."""

    relation: str
    accepted: int
    measured: int

    @property
    def interval_95(self) -> tuple[float, float] | None:
        """The Wilson 95% interval on the share accepted."""
        return wilson_interval(self.accepted, self.measured)


@dataclass(frozen=True, slots=True)
class Acceptance:
    """Correct-work acceptance: the share of correct rewritings the grader paid for."""

    #: 0-100, or None when no rewriting could be measured, which is not 100.
    score: float | None
    accepted: int
    measured: int
    #: One entry per relation measured, in the order they were first seen.
    relations: tuple[RelationResult, ...]

    @property
    def interval_95(self) -> tuple[float, float] | None:
        """The Wilson 95% interval on the share accepted, as a fraction."""
        return wilson_interval(self.accepted, self.measured)

    def __str__(self) -> str:
        interval = self.interval_95
        if self.score is None or interval is None:
            return "CORRECT-WORK ACCEPTANCE: not measured"
        low, high = interval
        return (
            f"CORRECT-WORK ACCEPTANCE: {self.score:.0f} / 100   95% CI {low * 100:.0f}–{high * 100:.0f}   "
            f"{self.accepted} of {self.measured} accepted   relations: {len(self.relations)}"
        )


@dataclass(frozen=True, slots=True)
class Exclusion:
    """A task left out of every rate, and why."""

    task_id: str
    shape: Shape
    reason: str


@dataclass(frozen=True, slots=True)
class ShapeScore:
    """The two numbers for one grader shape, or for all of them."""

    #: None for the overall line.
    shape: Shape | None
    #: Tasks of this shape that were scored (not excluded).
    tasks: int
    coverage: CoverageScore
    acceptance: Acceptance
    #: Weakness classes something in this run measured, in ID order.
    measured: tuple[str, ...]
    #: Weakness classes that apply to the shape and that nothing in this run measured.
    not_run: tuple[str, ...]

    def __str__(self) -> str:
        name = self.shape.value if self.shape is not None else "overall"
        lines = [f"{name}: {self.tasks} task{'' if self.tasks == 1 else 's'} scored", f"  {self.coverage}"]
        lines.append(f"  {self.acceptance}")
        if self.not_run:
            count = len(self.not_run)
            lines.append(
                f"  not run: {count} applicable weakness class{'' if count == 1 else 'es'}: {', '.join(self.not_run)}"
            )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Scorecard:
    """Every shape's two numbers, the overall pair, and every task left out."""

    shapes: tuple[ShapeScore, ...]
    overall: ShapeScore
    excluded: tuple[Exclusion, ...]

    def __str__(self) -> str:
        parts = [str(s) for s in self.shapes]
        if len(self.shapes) != 1:
            parts.append(str(self.overall))
        for exclusion in self.excluded:
            parts.append(f"not measured: {exclusion.task_id} ({exclusion.shape.value}): {exclusion.reason}")
        return "\n".join(parts)


def correct_work_acceptance(attempts: Iterable[ControlAttempt]) -> Acceptance:
    """The share of rewritings accepted, on tasks whose baseline was run and accepted.

    This applies the baseline gate and the could-not-run rule; it does not know about other
    attempts on the same tasks, so exclusions for a grader paying past full marks on a negative
    control are applied by :func:`scorecard`.
    """
    attempts = list(attempts)
    baseline_ok = _baseline_accepted(attempts)
    got: dict[tuple[str, str], bool] = {}
    for attempt in attempts:
        if attempt.control.baseline or attempt.accepted is None or attempt.task_id not in baseline_ok:
            continue
        key = (attempt.task_id, attempt.control.relation)
        # A rewriting tried more than once counts as accepted only if it was accepted every time.
        got[key] = got.get(key, True) and attempt.accepted

    order: list[str] = []
    for _task, relation in got:
        if relation not in order:
            order.append(relation)
    results = tuple(
        RelationResult(
            relation=r,
            accepted=sum(ok for (_t, rel), ok in got.items() if rel == r),
            measured=sum(1 for (_t, rel) in got if rel == r),
        )
        for r in order
    )
    measured = len(got)
    accepted = sum(got.values())
    score = 100.0 * accepted / measured if measured else None
    return Acceptance(score=score, accepted=accepted, measured=measured, relations=results)


def _baseline_accepted(attempts: Sequence[ControlAttempt]) -> set[str]:
    """Tasks whose baseline ran at least once and was never rejected."""
    ran: set[str] = set()
    rejected: set[str] = set()
    for attempt in attempts:
        if attempt.control.baseline and attempt.accepted is not None:
            ran.add(attempt.task_id)
            if not attempt.accepted:
                rejected.add(attempt.task_id)
    return ran - rejected


def scorecard(
    tasks: Iterable[Task],
    attempts: Iterable[Attempt],
    controls: Iterable[ControlAttempt] = (),
    operators: Sequence[MutationOperator] | None = None,
) -> Scorecard:
    """Score a grader per shape and overall, leaving out every task that cannot be scored soundly.

    ``tasks`` are every task in scope; ``attempts`` are the negative controls (the battery's
    candidates) and ``controls`` the positive controls, each with the grader's verdict. Raises
    ``ValueError`` for an attempt on a task not in ``tasks``, or for two tasks with one ID.
    """
    shape_of: dict[str, Shape] = {}
    for task in tasks:
        if task.id in shape_of:
            raise ValueError(f"two tasks have the ID {task.id!r}")
        shape_of[task.id] = task.shape
    attempts = list(attempts)
    controls = list(controls)
    for task_id in {a.task_id for a in attempts} | {c.task_id for c in controls}:
        if task_id not in shape_of:
            raise ValueError(f"an attempt names task {task_id!r}, which is not among the tasks")
    ops = list(operators) if operators is not None else discover()

    reasons: dict[str, str] = {}
    for c in controls:
        if c.control.baseline and c.accepted is False:
            reasons[c.task_id] = BASELINE_REJECTED
    for task_id in [a.task_id for a in attempts if a.scale_exceeded] + [
        c.task_id for c in controls if c.scale_exceeded
    ]:
        reasons.setdefault(task_id, PAST_FULL_MARKS)
    excluded = tuple(Exclusion(t, shape_of[t], reasons[t]) for t in shape_of if t in reasons)

    kept_attempts = [a for a in attempts if a.task_id not in reasons]
    kept_controls = [c for c in controls if c.task_id not in reasons]
    present = [s for s in Shape if s in shape_of.values()]
    per_shape = tuple(
        _shape_score(
            s,
            sum(1 for t, shape in shape_of.items() if shape == s and t not in reasons),
            [a for a in kept_attempts if shape_of[a.task_id] == s],
            [c for c in kept_controls if shape_of[c.task_id] == s],
            ops,
            (s,),
        )
        for s in present
    )
    overall = _shape_score(
        None, sum(1 for t in shape_of if t not in reasons), kept_attempts, kept_controls, ops, tuple(present)
    )
    return Scorecard(shapes=per_shape, overall=overall, excluded=excluded)


def _shape_score(
    shape: Shape | None,
    tasks: int,
    attempts: list[Attempt],
    controls: list[ControlAttempt],
    ops: Sequence[MutationOperator],
    applicable_shapes: tuple[Shape, ...],
) -> ShapeScore:
    coverage = coverage_score(attempts, ops)
    acceptance = correct_work_acceptance(controls)
    measured = _measured_weaknesses(attempts, controls)
    applicable = {
        w.id
        for w in weakness_list().weaknesses
        if w.status == "active" and w.family in CATEGORIES and any(s in w.shapes for s in applicable_shapes)
    }
    return ShapeScore(
        shape=shape,
        tasks=tasks,
        coverage=coverage,
        acceptance=acceptance,
        measured=_by_number(measured),
        not_run=_by_number(applicable - measured),
    )


def _measured_weaknesses(attempts: list[Attempt], controls: list[ControlAttempt]) -> set[str]:
    """The weakness classes named by the manifests of the probes that produced a counted result."""
    operators = {
        a.candidate.provenance.operator for a in attempts if a.candidate.known_wrong and a.accepted is not None
    }
    baseline_ok = _baseline_accepted(controls)
    operators |= {
        c.control.relation
        for c in controls
        if c.accepted is not None and (c.control.baseline or c.task_id in baseline_ok)
    }
    found: set[str] = set()
    for operator in operators:
        probe = probe_for(operator)
        if probe is not None:
            found.update(probe.weakness)
    return found


def _by_number(ids: set[str]) -> tuple[str, ...]:
    return tuple(sorted(ids, key=weakness_number))


__all__ = [
    "BASELINE_REJECTED",
    "PAST_FULL_MARKS",
    "Acceptance",
    "ControlAttempt",
    "Exclusion",
    "RelationResult",
    "Scorecard",
    "ShapeScore",
    "correct_work_acceptance",
    "scorecard",
]
