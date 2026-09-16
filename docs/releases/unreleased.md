---
title: "Bohrin — unreleased"
version: "unreleased"
date: "unreleased"
# tag: "vX.Y.Z"        # add at release time
breaking: false
summary: >
  States what is open in Bohrin and how new checks ship.
---

## TL;DR

The public boundary page now matches the code: four open probes, nine operators and
seventeen answer relations. It also says what this repository accepts. Nothing to do on
upgrade.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** none — `pip install --upgrade 'bohrin[verifiers]'`
- **New minimums:** none

## Highlights

- **What is open, stated accurately** — `docs/04_RELEASE.md` listed two open probes while four ship. It now lists everything that is open and explains how the open check set changes.

## Added

- …

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
