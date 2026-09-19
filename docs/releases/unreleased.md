---
title: "Bohrin X.Y.Z"
version: "X.Y.Z"
date: "unreleased"
# tag: "vX.Y.Z"        # add at release time
breaking: false
summary: >
  Text from an audited taskset can no longer control your terminal.
---

## TL;DR

A security fix. A taskset under audit could embed terminal control sequences in a task id,
prompt or error message, and Bohrin printed them live: enough to clear the screen or erase
the line reporting that taskset's own exploit. They are now shown, not obeyed. Nothing to do
on upgrade.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** none — `pip install --upgrade 'bohrin[verifiers]'`
- **New minimums:** none

## Highlights

- **Terminal output is safe from the taskset being audited** — control sequences in task ids, prompts, answers and grader errors are displayed as visible escapes instead of being executed by your terminal.

## Added

- …

## Changed

- …

## Security

- **Text from an audited taskset can no longer control your terminal.** Bohrin prints strings it
  did not write: task ids, prompts, declared answers, submitted payloads and the grader's own error
  messages. Rich markup was already escaped, but terminal control sequences were not, and Rich
  passes CSI sequences through. Measured: a task id containing `\x1b[2J` reached the terminal intact
  on three report lines, including the reproduction command. A hostile taskset could have cleared
  the screen, moved the cursor up and erased the line reporting its own exploit, or printed a forged
  line. Every control character and bidirectional override is now shown as a visible escape such as
  `\x1b`, in the report and in error messages alike.
- **Reproduction commands stay exact.** Ordinary arguments are quoted exactly as before. An argument
  containing a control character is written in ANSI-C quoting (`$'...'`), which bash and zsh decode
  back to the original bytes, so a pasted command still re-runs the same task.

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
