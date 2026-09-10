---
title: "Bohrin — unreleased"
version: "unreleased"
date: "unreleased"
# tag: "vX.Y.Z"        # add at release time
breaking: false
summary: >
  One sentence shown on the changelog index. What this release is, in plain terms.
---

## TL;DR

One short paragraph a reader skims in five seconds: what this release is, and
whether they need to do anything to upgrade.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** none — `pip install --upgrade 'bohrin[verifiers]'`
- **New minimums:** none

## Highlights

- **<the change>** (#NN) — why it matters to a user, in one or two sentences.

## Added

- …

## Changed

- …

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
