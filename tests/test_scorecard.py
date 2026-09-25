"""The scorecard: two numbers per shape, never merged, over only the tasks that can be scored.

Each rule is held from both directions. A correct grader scores 100 on both numbers; a grader that
only accepts the reference's exact text catches every cheat and is exposed by correct-work
acceptance. Each exclusion (the reference rejected, a reward past full marks, an attempt that could
not run) has a test that fails when its guard is removed: without it, a broken task would be
scored as a grader catching cheats.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

import pytest

from _fixtures import REFERENCE, behavioural_grader, task
from bohrin.ir.task import Candidate, Ground, Provenance, Shape, Source, Task
from bohrin.mutate.battery import battery
from bohrin.relations import BASELINE, Control, positive_controls
from bohrin.scoring.coverage import Attempt, coverage_score
from bohrin.scoring.scorecard import (
    BASELINE_REJECTED,
    PAST_FULL_MARKS,
    ControlAttempt,
    ShapeScore,
    correct_work_acceptance,
    scorecard,
)

#: A second program, with a comment so every relation has something to rewrite.
DOUBLE = "def solve(n):\n    # doubles\n    result = n * 2\n    return result\n"
_INPUTS = {REFERENCE: ((), (1, -2, 3), (0,)), DOUBLE: (0, 3, -4)}


def _tasks(*shapes: Shape) -> list[Task]:
    sources = [REFERENCE, DOUBLE]
    return [task(sources[i % 2], task_id=f"t{i}", shape=s) for i, s in enumerate(shapes)]


def _run(
    tasks: Iterable[Task], grades: Callable[[Task], Callable[[str], bool | None]]
) -> tuple[list[Attempt], list[ControlAttempt]]:
    attempts: list[Attempt] = []
    controls: list[ControlAttempt] = []
    for t in tasks:
        grade = grades(t)
        attempts += [Attempt(t.id, c, grade(_text(c.payload))) for c in battery(t).candidates]
        controls += [ControlAttempt(t.id, c, grade(c.payload.text)) for c in positive_controls(t)]
    return attempts, controls


def _text(payload: object) -> str:
    assert isinstance(payload, Source)
    return payload.text


def _correct(t: Task) -> Callable[[str], bool]:
    assert t.reference is not None
    return behavioural_grader(t.reference, _INPUTS[t.reference])


def _exact_text(t: Task) -> Callable[[str], bool]:
    """Catches every cheat by accepting nothing but the reference, byte for byte (BGW-120)."""
    return lambda submission: submission == t.reference


# --------------------------------------------------------------------------- the two numbers


def test_a_correct_grader_scores_full_marks_on_both_numbers() -> None:
    tasks = _tasks(Shape.PROGRAM, Shape.PROGRAM)
    card = scorecard(tasks, *_run(tasks, _correct))

    assert card.overall.coverage.score == 100.0
    assert card.overall.acceptance.score == 100.0
    assert card.overall.acceptance.measured >= 4, "every certified rewriting was measured"
    assert card.excluded == ()


def test_a_grader_that_only_accepts_the_exact_reference_is_exposed() -> None:
    """It catches every cheat, which is exactly why the Coverage Score alone cannot be the grade."""
    tasks = _tasks(Shape.PROGRAM, Shape.PROGRAM)
    card = scorecard(tasks, *_run(tasks, _exact_text))

    assert card.overall.coverage.score == 100.0
    assert card.overall.acceptance.score == 0.0
    assert card.overall.acceptance.measured > 0


def test_the_baseline_gates_acceptance_but_is_never_counted_in_it() -> None:
    """Counting the reference itself would give every scored task a free success."""
    tasks = _tasks(Shape.PROGRAM)
    _, controls = _run(tasks, _exact_text)
    acceptance = correct_work_acceptance(controls)

    assert BASELINE not in [r.relation for r in acceptance.relations]
    assert acceptance.accepted == 0


def test_acceptance_is_not_measured_where_the_baseline_was_not_run() -> None:
    """A rejected rewriting says nothing if the reference itself was never shown to pass."""
    tasks = _tasks(Shape.PROGRAM)
    attempts, controls = _run(tasks, _exact_text)
    card = scorecard(tasks, attempts, [c for c in controls if not c.control.baseline])

    assert card.overall.acceptance.score is None
    assert "CORRECT-WORK ACCEPTANCE: not measured" in str(card)
    assert card.overall.coverage.score == 100.0, "coverage is still scored: the baseline was not rejected"
    assert card.excluded == ()


def test_a_rewriting_counts_as_accepted_only_if_it_was_accepted_every_time() -> None:
    t = task(REFERENCE)
    baseline, rewriting = positive_controls(t)[:2]
    # Rejected first, then accepted: a score keeping only the latest verdict would count it.
    flaky = [ControlAttempt(t.id, baseline, True), ControlAttempt(t.id, rewriting, False)]
    flaky.append(ControlAttempt(t.id, rewriting, True))
    acceptance = correct_work_acceptance(flaky)

    assert (acceptance.accepted, acceptance.measured) == (0, 1)


def test_acceptance_alone_measures_nothing_on_a_task_whose_reference_was_rejected() -> None:
    """The baseline gate holds for correct_work_acceptance on its own, without the scorecard."""
    t = task(REFERENCE)
    baseline, *rewritings = positive_controls(t)
    attempts = [ControlAttempt(t.id, baseline, False)] + [ControlAttempt(t.id, r, False) for r in rewritings]

    assert correct_work_acceptance(attempts).score is None


def test_each_relation_carries_its_own_sample_and_interval() -> None:
    tasks = _tasks(Shape.PROGRAM, Shape.PROGRAM)
    _, controls = _run(tasks, _correct)
    measured = {r.relation: r.measured for r in correct_work_acceptance(controls).relations}
    # REFERENCE has no comments, so only DOUBLE has a comment-free rewriting; and on DOUBLE the
    # re-laid-out program is that same text, so it is sent once, credited to the smaller change.
    assert measured == {"comment_free": 1, "reformatted": 1, "renamed_locals": 2}
    assert all(r.interval_95 is not None for r in correct_work_acceptance(controls).relations)


def test_a_shape_with_nothing_left_unmeasured_prints_no_not_run_line() -> None:
    measured = scorecard([task(REFERENCE)], []).overall
    complete = ShapeScore(Shape.PROGRAM, 0, measured.coverage, measured.acceptance, measured=(), not_run=())

    assert "not run" not in str(complete)


def test_nothing_measured_is_not_perfect() -> None:
    card = scorecard([task(REFERENCE)], [], [])

    assert card.overall.coverage.score is None and card.overall.acceptance.score is None
    assert correct_work_acceptance([]).interval_95 is None


# --------------------------------------------------------------------------- exclusions


def test_a_task_whose_reference_is_rejected_is_left_out_of_both_numbers() -> None:
    """I4. The grader rejects the reference and every cheat; that is not catching cheats."""
    tasks = _tasks(Shape.PROGRAM)
    card = scorecard(tasks, *_run(tasks, lambda _t: lambda _submission: False))

    assert card.overall.coverage.score is None, "a broken task must not score as a grader catching everything"
    assert card.overall.acceptance.score is None
    assert [(e.task_id, e.reason) for e in card.excluded] == [("t0", BASELINE_REJECTED)]
    assert f"not measured: t0 (program): {BASELINE_REJECTED}" in str(card)


def test_a_baseline_rejected_once_among_several_runs_excludes_the_task() -> None:
    t = task(REFERENCE)
    baseline = positive_controls(t)[0]
    runs = [ControlAttempt(t.id, baseline, True), ControlAttempt(t.id, baseline, False)]

    assert [e.reason for e in scorecard([t], [], runs).excluded] == [BASELINE_REJECTED]


def test_a_task_where_the_grader_paid_past_full_marks_is_left_out() -> None:
    """I5. Full marks are not known there, so neither a catch nor an acceptance can be read."""
    tasks = _tasks(Shape.PROGRAM, Shape.PROGRAM)
    attempts, controls = _run(tasks, _correct)
    attempts[0] = Attempt(attempts[0].task_id, attempts[0].candidate, True, scale_exceeded=True)
    card = scorecard(tasks, attempts, controls)

    assert [(e.task_id, e.reason) for e in card.excluded] == [("t0", PAST_FULL_MARKS)]
    assert card.overall.coverage.score == 100.0, "the accepted attempt past full marks is not an accusation"
    assert card.overall.tasks == 1


def test_a_positive_control_past_full_marks_excludes_the_task_too() -> None:
    tasks = _tasks(Shape.PROGRAM)
    attempts, controls = _run(tasks, _correct)
    controls[1] = ControlAttempt(controls[1].task_id, controls[1].control, True, scale_exceeded=True)

    assert [e.reason for e in scorecard(tasks, attempts, controls).excluded] == [PAST_FULL_MARKS]


def test_coverage_alone_leaves_out_a_task_paid_past_full_marks() -> None:
    """I5 holds for the Coverage Score on its own, not only inside the scorecard."""
    t = task(REFERENCE)
    candidate = battery(t).candidates[0]
    other = Candidate(Source("pass\n"), Provenance("drop_side_effect", "reference", "second"), Ground.STRUCTURAL)
    attempts = [Attempt(t.id, candidate, False), Attempt(t.id, other, True, scale_exceeded=True)]

    assert coverage_score(attempts).score is None


def test_an_attempt_that_could_not_run_is_never_a_catch() -> None:
    """I6. A crash left in as "rejected" would score a broken run as a grader catching cheats."""
    tasks = _tasks(Shape.PROGRAM)
    attempts, controls = _run(tasks, lambda _t: lambda _submission: None)

    assert coverage_score(attempts).score is None
    card = scorecard(tasks, attempts, controls)
    assert card.overall.coverage.score is None and card.overall.acceptance.score is None
    assert card.excluded == (), "could-not-run is not a rejected reference"


def test_the_exclusion_guard_is_load_bearing() -> None:
    """Remove the I4 reason and the broken task is scored as 100: the guard is what stops that."""
    tasks = _tasks(Shape.PROGRAM)
    attempts, controls = _run(tasks, lambda _t: lambda _submission: False)
    unguarded = [
        ControlAttempt(c.task_id, Control(c.control.payload, "not_the_baseline", ""), c.accepted) for c in controls
    ]

    assert scorecard(tasks, attempts, unguarded).overall.coverage.score == 100.0
    assert scorecard(tasks, attempts, controls).overall.coverage.score is None


# --------------------------------------------------------------------------- per shape


def test_each_shape_gets_its_own_numbers_then_overall() -> None:
    tasks = _tasks(Shape.PROGRAM, Shape.WORKSPACE)
    card = scorecard(tasks, *_run(tasks, _correct))

    assert [s.shape for s in card.shapes] == [Shape.PROGRAM, Shape.WORKSPACE]
    assert [s.tasks for s in card.shapes] == [1, 1] and card.overall.tasks == 2
    assert card.overall.coverage.measured == sum(s.coverage.measured for s in card.shapes)
    rendered = str(card)
    assert rendered.index("program:") < rendered.index("workspace:") < rendered.index("overall:")


def test_one_shape_prints_no_separate_overall_line() -> None:
    tasks = _tasks(Shape.PROGRAM)
    rendered = str(scorecard(tasks, *_run(tasks, _correct)))

    assert "overall:" not in rendered
    assert "COVERAGE SCORE: 100 / 100" in rendered and "CORRECT-WORK ACCEPTANCE: 100 / 100" in rendered


def test_every_shape_names_the_weaknesses_it_did_not_measure() -> None:
    tasks = _tasks(Shape.PROGRAM, Shape.WORKSPACE)
    card = scorecard(tasks, *_run(tasks, _correct))
    program, workspace = card.shapes

    assert {"BGW-101", "BGW-120", "BGW-124"} <= set(program.measured)
    assert not set(program.measured) & set(program.not_run)
    assert "BGW-102" in program.not_run, "an applicable class nothing tried is named, not hidden"
    assert "BGW-108" in workspace.not_run and "BGW-108" not in program.not_run, "only classes the shape can have"
    assert f"not run: {len(program.not_run)} applicable weakness classes: BGW-102" in str(card)


def test_a_lead_or_an_unmanifested_operator_measures_no_weakness() -> None:
    t = task(REFERENCE)
    lead = Candidate(Source("x"), Provenance("drop_side_effect", "reference", "unproven"), None)
    unknown = Candidate(Source("y"), Provenance("third_party", "reference", "no manifest"), Ground.STRUCTURAL)
    card = scorecard([t], [Attempt(t.id, lead, False), Attempt(t.id, unknown, False)])

    assert card.overall.measured == ()


# --------------------------------------------------------------------------- inputs


def test_two_tasks_with_one_id_are_refused() -> None:
    with pytest.raises(ValueError, match="two tasks"):
        scorecard([task(REFERENCE), task(REFERENCE)], [])


def test_an_attempt_on_an_unknown_task_is_refused() -> None:
    t = task(REFERENCE)
    control = positive_controls(t)[0]
    with pytest.raises(ValueError, match="not among the tasks"):
        scorecard([t], [], [ControlAttempt("elsewhere", control, True)])


def test_the_package_exports_the_types_without_hiding_the_module() -> None:
    """Like ``bohrin.mutate.battery``, the function stays in its module, so the name is never shadowed."""
    import sys

    from bohrin import scoring

    module = sys.modules["bohrin.scoring.scorecard"]
    for name in ("Acceptance", "ControlAttempt", "Scorecard", "correct_work_acceptance"):
        assert getattr(scoring, name) is getattr(module, name)
    assert scoring.scorecard is module
