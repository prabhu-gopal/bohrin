---
title: "Bohrin — unreleased"
version: "unreleased"
date: "unreleased"
# tag: "vX.Y.Z"        # add at release time
breaking: false
summary: >
  Two fixes from hand-verifying the first index sweep: weak graders that read clean are now
  caught, and graders that score past 1 are no longer accused.
---

## TL;DR

Before publishing an index, Bohrin's own findings on 20 public environments were checked by
hand, flagged and clean alike. That turned up one way a weak grader read clean and one way a
grader Bohrin could not judge was reported as exploited. This release fixes both. No action
is needed to upgrade.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** none — `pip install --upgrade 'bohrin[verifiers]'`
- **New minimums:** none — `--json` consumers see report schema **1.4**, which only adds a key

## Highlights

- **Graders that read the start of a reply are now caught.** Before this, a grader that
  only checked what a reply *begins* with could read clean while paying full marks for a
  reply that denies the right answer.
- **No more false exploits on rubrics that score past 1.** A grader that sums or averages
  scores above 1 is now reported as *not measured* rather than as broken.

## Added

- **`--sample-seed N`: audit a random sample, not the first N tasks.** `--max-tasks N`
  audits the *first* N, which is a statement about those N and nothing else — measured on a
  published environment, a bound of 10 scored 0 while a bound of 20 scored 50 on the same
  verifier, because the tasks carrying the defect sat at positions 11 and 12. Tasksets are
  also commonly ordered by subject or source, so the opening tasks are not a haphazard
  slice. With a seed, the tasks are drawn uniformly at random, so the rate estimates the
  whole taskset and the interval beside it means what it says. The report prints how the
  tasks were chosen — `100 random of 3270 tasks (seed 7)` — and records it in `--json`, and
  the same seed redraws the same sample, so a published number stays reproducible. A
  taskset that will not report its length cannot be sampled, and that run is refused rather
  than quietly given a prefix. Without the flag, nothing changes.

## Fixed

- **`false_negation` now also puts the answer first.** Its denials all opened with `The`
  — `The answer is not A.` — which catches a grader that looks for the answer anywhere in
  the reply, but never one that reads the first label, or checks that the reply starts
  with the answer. The first index sweep's hand-verification checks a sample of *clean*
  results as well as flagged ones, because a false clean is the failure an auditing tool
  can least afford. It found two public multiple-choice environments that read clean at 0
  of 100 tasks, whose graders — called directly, with Bohrin not installed — paid full
  reward for `A is not the answer.` on 100 of 100 tasks. Two new forms, `X is not the
  answer.` and `X is wrong.`, now reach them. Each still contradicts the declared answer,
  so a correct grader is no more exposed than before: an exact-match grader rejects all
  four forms.

- **A rubric that pays past its own full marks is no longer read as exploited.** Bohrin
  counts a reply as accepted when its reward reaches full marks, and it reads full marks
  from the rubric's weights, which assume every reward function returns between 0 and 1.
  Some don't: the same hand-verification found one public environment that sums five
  criteria scored 0–3 (worth up to 15) and one that averages 1–5 ratings. On both,
  ordinary replies cleared a bar of 1 — a prompt echo scored 12 of 15 on the first — and were
  reported as full-marks exploits. Bohrin cannot read a rubric's true scale, so a task on
  which any reply, the reference included, scores above full marks is now left out of the
  measurement, and anything it accepted is shown as a lead. If that leaves nothing, the
  probe says *not measured*, never clean.

## Changed

- **Report schema 1.4.** `weak_oracle`'s `detail` gains `tasks_scale_unknown`. Additive.

## Known limitations

- A grader that reads only one answer format — typically the last `\boxed{}` — still
  reads clean whether or not it is weak. Bohrin's payloads are not written in it.
- On a rubric that scores past 1, a real defect is now reported as a lead rather than an
  exploit. One of the two environments above gives an empty reply its maximum score, which
  is a genuine weakness; Bohrin can no longer claim it, because doing so needs the scale it
  cannot read.

## Verified

- `ruff check` · `ruff format --check` · `mypy --strict` · `pytest` — all clean
- Eight new tests. A prefix grader and a first-label grader are each caught; every denial
  form contradicts the answer rather than restating it; an exact-match grader is untouched.
  A rating-mean grader and a criteria-sum grader are no longer accused; only the off-scale
  task leaves the denominator; an ordinary 0–1 grader is measured exactly as before.
- Real environments, each fix installed into a fresh venv per environment, cap 100: the
  two clean-reading multiple-choice environments went from 0/100 to 100/100; the two
  off-scale environments went from "exploited" to *not measured*; four controls were
  unchanged at 100/100.

## Links

- Full changelog entry: [CHANGELOG.md](../../CHANGELOG.md)
- Compare: `v1.2.0...vX.Y.Z`
- PRs in this release: #57, #NN
