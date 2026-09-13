---
title: "Bohrin — unreleased"
version: "unreleased"
date: "unreleased"
# tag: "vX.Y.Z"        # add at release time
breaking: false
summary: >
  Documentation corrections only: the README now names the `verifiers` API most
  environments actually use, and the "what we still miss" paragraph describes the blind
  spot that is open rather than the one 1.3.0 closed.
---

## TL;DR

No code changed. Six documentation defects found by auditing the repository against the
released 1.3.0 — the most costly being that the README described Bohrin as reading only
`verifiers` v1 tasksets, when the API most published environments expose is
`load_environment`, supported since 1.2.0. Nothing to upgrade.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** none
- **New minimums:** none

## Fixed

- **The README now says Bohrin reads both `verifiers` APIs.** It named only v1 tasksets and
  never mentioned `load_environment` — the entry point most published environments expose,
  and the one 1.2.0 added support for after recognising 0 of 109 environments without it. A
  maintainer with a `load_environment` environment would have read that page and concluded
  Bohrin could not audit their code. The page now names both, says which one the report
  header reports, and gives the `verifiers<0.3.2` pin for environments that resolve past
  upstream's removal of the legacy entry point.

- **The "honest edge of the open core" paragraph described a blind spot that 1.3.0 closed.**
  A grader reading only the last `\boxed{}` is now probed in that format, because the
  baseline learns it from the verifier's own acceptance of the declared answer. Both the
  README and `docs/05_ROBUSTNESS.md` still named it as the boundary that remains. They now
  name the real one: a task declaring no answer, where no baseline runs and so no format can
  be learned.

- **The operator count is seven, not six**, in the README and `docs/05_ROBUSTNESS.md`.
  `false_negation` was not counted.

- **Seven references to a version that was never released.** The September fixes were
  planned as 1.2.1 and shipped as 1.3.0; two of the stale references were in the public
  probe documentation.

- **`SECURITY.md` listed 1.1.x as the supported line**, and the open/closed boundary table
  in `docs/04_RELEASE.md` described the adapter row as v1-only.

## Verified

- `ruff check` · `ruff format --check` · `mypy --strict` · `pytest` — all clean
- Every corrected claim checked against the code rather than recalled: seven operators
  registered under `bohrin.mutators` in `pyproject.toml`, and no reference to `1.2.1`
  remaining anywhere outside the changelog's historical entries.

## Links

- Full changelog entry: [CHANGELOG.md](../../CHANGELOG.md)
- Compare: `v1.3.0...vX.Y.Z`
