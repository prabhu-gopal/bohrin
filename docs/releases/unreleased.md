---
title: "Bohrin — unreleased"
version: "unreleased"
date: "unreleased"
# tag: "vX.Y.Z"        # add at release time
breaking: false
summary: >
  Flags that cannot measure anything now fail instead of passing in silence, and the README
  names the `verifiers` API most environments actually use.
---

## TL;DR

Found by auditing the released 1.3.0 before running the index sweep on it. Seven CLI values
that measure nothing used to start an audit and exit 0 — a green CI build with nothing
behind it — and now exit 2. Six documentation defects are also fixed, the most costly being
that the README described Bohrin as reading only `verifiers` v1 tasksets, when most
published environments expose `load_environment`, supported since 1.2.0.

## Upgrade impact

- **Breaking changes:** none — every refused value was already producing an audit that
  measured nothing
- **Action required:** only if a script passes one of the refused values. It will now exit
  2 instead of 0; that run was never measuring anything, so fix the value — most often by
  adding `--max-tasks N` beside an existing `--sample-seed`
- **New minimums:** none

## Fixed

- **A mistyped flag now fails instead of passing.** `--max-tasks 0`, `--repeats 0`,
  `--timeout 0`, a negative `--concurrency`, and a `--fail-on-gap` outside 0–100 each used
  to start an audit that measured nothing and exited 0, which in CI looks exactly like a
  clean result. `--fail-on-gap 150` was the quietest of them: a gate that can never close.
  All of them now exit 2 with a message naming the flag and what it accepts.
- **`--sample-seed` without `--max-tasks` is refused.** A seed chooses *which* tasks to
  take, so without a bound it has nothing to choose — and it was ignored without a word:
  asking for a sample of a 3270-task environment audited all 3270 and recorded no seed. It
  now tells you to add `--max-tasks N`.
- **The README's example is a real 1.3.0 run again**, including the confidence intervals
  and the `rests on:` line it had been missing.

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
