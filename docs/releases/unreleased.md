---
title: "Bohrin — unreleased"
version: "unreleased"
date: "unreleased"
# tag: "vX.Y.Z"        # add at release time
breaking: false
summary: >
  Audits Inspect evaluations, and states what is open in Bohrin.
---

## TL;DR

Bohrin now reads Inspect evaluations as well as `verifiers` environments. The public
boundary page also matches the code again. Nothing to do on upgrade; install the new
`inspect` extra to audit Inspect tasks.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** none — `pip install --upgrade 'bohrin[verifiers]'`
- **New minimums:** none

## Highlights

- **Audit Inspect evaluations** — point `bohrin audit` at a file defining `@task` functions and each scorer is tested with the same checks as a `verifiers` reward function, without running a model.
- **What is open, stated accurately** — `docs/04_RELEASE.md` listed two open probes while four ship. It now lists everything that is open and explains how the open check set changes.

## Added

- **The `inspect` adapter.** `pip install 'bohrin[inspect]'`, then `bohrin audit` a file or
  directory of Inspect `@task` functions. Each sample becomes a task, with its target as the
  declared answer. Scorers are called directly with the candidate as the model's reply.
  Tasks built with no arguments are read.
- **Scorers Bohrin cannot grade offline are refused, never guessed at.** A task that runs in a
  sandbox, the model-graded built-in scorers, and `choice` (which grades what the
  multiple-choice solver marks) are refused before scoring. A custom scorer that asks a model
  or a sandbox while grading — for example a judge used only when an exact match fails — has
  that submission declined, even when the scorer catches the failure and returns "incorrect".
- **Declined submissions are never reported as crashes.** Adapters can now decline to score a
  single submission (`ScoringRefused`). Without that, a judge Bohrin refused to call would be
  reported as the grader crashing on Bohrin's input.

## Changed

- **The open check set is complete as shipped.** The repository accepts accuracy fixes,
  adapters and integrations, report renderers and bug fixes. New probes and operators are
  published as separate packages through the public `bohrin.probes` and `bohrin.mutators`
  entry points, the same mechanism the built-in checks use. `CONTRIBUTING.md` says the same.

## Fixed

- …

## Removed

- …

## Known limitations

- …

## Verified

- `ruff check` · `ruff format --check` · `mypy --strict` · `pytest` — all clean
- `pip install 'bohrin[verifiers]'` in a fresh venv, then `bohrin audit <a real public taskset>` — produced <result> in <time>

## Links

- Full changelog entry: [CHANGELOG.md](../../CHANGELOG.md)
- Compare: `vPREV...vX.Y.Z`
- PRs in this release: #NN
