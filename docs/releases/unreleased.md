---
title: "Bohrin — unreleased"
version: "unreleased"
date: "unreleased"
# tag: "vX.Y.Z"        # add at release time
breaking: false
summary: >
  Fixes found by auditing 57 public environments: Bohrin no longer hangs after its report.
---

## TL;DR

Engine fixes found while running Bohrin across 57 public environments. The most visible: on
some environments the `bohrin` command printed its report or error and then never exited,
which hangs a CI job. Nothing to change on upgrade.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** none — `pip install --upgrade 'bohrin[verifiers]'`
- **New minimums:** none

## Highlights

- **`bohrin` exits when it is done.** A hang after the report, inherited from a library the
  environment loads, can no longer keep your terminal or CI job waiting.

## Added

- **Bohrin now recognises `Final Answer: X`.** Some graders only accept an answer written as
  `Final Answer: B`, usually because the prompt asks for exactly that. Bohrin learns the
  format a grader wants by trying presentations of your declared answer, and this one was
  missing, so such a grader could never be measured. It is now tried, after every existing
  presentation. On the public environment that exposed the gap, it also revealed a weakness:
  the grader pays full marks for `Final Answer: B is not the answer.`

## Changed

- …

## Fixed

- **No more hang after the report.** On one public environment, Bohrin printed its load
  error and the process then sat for 11 minutes until it was stopped. The cause was not in
  Bohrin: after the environment's dataset build failed, a data library it uses (Apache
  Arrow) waited forever while the process was shutting down, and plain Python without Bohrin
  hung the same way. But the hung terminal was Bohrin's, so the `bohrin` command now ends
  its process as soon as its output is written. Reports and `--json` files are written
  first, and every exit code is unchanged.

## Removed

- …

## Known limitations

- …

## Verified

- `ruff check` · `ruff format --check` · `mypy --strict` · `pytest` — all clean
- `pip install 'bohrin[verifiers]'` in a fresh venv, then `bohrin audit <a real public taskset>` — produced <result> in <time>

## Links

- Full changelog entry: [CHANGELOG.md](../../CHANGELOG.md)
- Compare: `v1.3.1...vX.Y.Z`
- PRs in this release: #NN
