---
title: "Bohrin — unreleased"
version: "unreleased"
date: "unreleased"
# tag: "vX.Y.Z"        # add at release time
breaking: false
summary: >
  Closes a way a weak grader could read clean: denials now also put the answer first.
---

## TL;DR

Hand-verifying the first index sweep turned up graders Bohrin reported clean that are
not. This release closes that gap. No action is needed to upgrade.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** none — `pip install --upgrade 'bohrin[verifiers]'`
- **New minimums:** none

## Highlights

- **Graders that read the start of a reply are now caught.** Before this, a grader that
  only checked what a reply *begins* with could read clean while paying full marks for a
  reply that denies the right answer.

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

## Known limitations

- A grader that reads only one answer format — typically the last `\boxed{}` — still
  reads clean whether or not it is weak. Bohrin's payloads are not written in it.

## Verified

- `ruff check` · `ruff format --check` · `mypy --strict` · `pytest` — all clean
- Four new tests: a prefix grader and a first-label grader are each caught, every denial
  form contradicts the answer rather than restating it, and an exact-match grader is
  untouched.

## Links

- Full changelog entry: [CHANGELOG.md](../../CHANGELOG.md)
- Compare: `v1.2.0...vX.Y.Z`
- PRs in this release: #NN
