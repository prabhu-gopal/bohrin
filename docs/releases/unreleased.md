---
title: "Bohrin X.Y.Z"
version: "X.Y.Z"
date: "unreleased"
# tag: "vX.Y.Z"        # add at release time
breaking: false
summary: >
  Adds the Coverage Score: what fraction of the ways a task can be passed without doing it a grader catches.
---

## TL;DR

Adds the Coverage Score, a 0–100 grade for a grader: of the known ways a task can be passed
without doing it, what fraction the grader caught. Nothing to do on upgrade.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** none — `pip install --upgrade bohrin`
- **New minimums:** none

## Highlights

- **The Coverage Score** — one number a grader's author can read as a grade, that never claims
  more than was tried: it names the categories it covered and carries its own interval.

## Added

- **`scoring.coverage.coverage_score`.** Offer each candidate from `battery(task)` to your grader,
  record whether it paid full marks, and pass the attempts in. The score is computed per task and
  category — `empty_and_echo`, `denial`, `multiple_answers`, `malformed_output`, `wrong_answer`,
  published as battery `1`. A category is caught on a task only if every grounded candidate in it
  was rejected: rejecting three denials and paying for the fourth has not caught denial.
- **`MutationOperator.category`.** Every built-in operator declares the category its candidates
  count towards. A third-party operator that declares none counts as `other`, and is never
  claimed as coverage of a published category.

## Known limitations

- The score covers what the battery can construct. A clean 100 bounds what was tried; it is not a
  proof that the grader is sound.

## Verified

- `ruff check` · `ruff format --check` · `mypy --strict` · `pytest` — all clean
- `pip install bohrin` in a fresh venv, then the battery against a real public grader — produced <result>

## Links

- Full changelog entry: [CHANGELOG.md](../../CHANGELOG.md)
- Compare: `vPREV...vX.Y.Z`
- PRs in this release: #NN
