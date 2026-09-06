---
title: "Bohrin — unreleased"
version: "unreleased"
date: "unreleased"
breaking: false
summary: >
  Housekeeping: an unused dependency removed, documentation brought back in sync with the
  code, and a release-notes process added.
---

## TL;DR

Nothing in how Bohrin runs changes here. `pyyaml` — declared but never imported —
is removed, several docs that had drifted from the code are corrected, and this
folder (per-release notes for the website) is introduced.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** none
- **New minimums:** none

## Changed

- **`pyyaml` is no longer a declared dependency** (#23). It was listed for a
  `bohrin.yaml` config file that was never built, so nothing in `src/bohrin/`
  imported it — which broke this project's own rule that every declared
  dependency is imported by a line of code. `types-PyYAML` is dropped from the
  dev extra for the same reason. A per-project config file can reintroduce it
  when a user asks. `pyyaml` still resolves transitively through the `verifiers`
  extra, so nothing at runtime changes.

## Fixed

- **Documentation now matches the code** (#23). `execute/runner.py` claimed a
  Python 3.10 floor (it is 3.11) and pinned the `gather`-over-`TaskGroup` choice
  on that; the real reason — `TaskGroup` cancels every sibling when one task
  raises, which would abandon an audit over a single hung verifier — is now in
  the docstring. `docs/01_ARCHITECTURE.md` referenced two report modules that do
  not exist and showed core types that had drifted from `ir/task.py`.
  `docs/03_PROBES.md` listed seven mutation operators, two of which
  (`off_by_one`, `swap_operator`) are deliberately unregistered, and omitted
  `refusal`, which ships. `CONTRIBUTING.md` named Python 3.10 as supported.

## Added

- **`docs/releases/`** — one Markdown file per released version, written for
  people who use Bohrin, feeding the website's changelog page. See
  [`docs/releases/README.md`](./README.md) for the format and the process.

## Verified

- `ruff check` · `ruff format --check` · `mypy --strict` · `pytest` (72 passed)
  · `uv build` · `bohrin` CLI surface (`--version`, `list-probes`, `explain`, a
  bad-path error) — all clean.

## Links

- Full changelog entry: [CHANGELOG.md → Unreleased](../../CHANGELOG.md)
- PRs: #23
