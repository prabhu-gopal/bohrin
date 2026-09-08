---
title: "Bohrin — unreleased"
version: "unreleased"
date: "unreleased"
# tag: "vX.Y.Z"        # add at release time
breaking: false
summary: >
  Bohrin's answer renderings become a declared, extensible catalogue of metamorphic
  relations — each one carrying the argument for why it preserves meaning, and each one
  silent on answers it does not apply to.
---

## TL;DR

The eight hard-coded ways Bohrin re-renders an answer when looking for one its verifier
accepts are now a **declared catalogue of metamorphic relations** — twelve of them, each
stating why its rewriting preserves meaning, each staying silent on answers it does not
apply to, and all of them extensible by a third party without patching Bohrin.

Nothing changes about how an audit runs today. This is the groundwork for reporting the
other half of the gap: verifiers that reject answers that are correct.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** none — `pip install --upgrade 'bohrin[verifiers]'`
- **New minimums:** none
- **Baselines try four more renderings than before** (`inline_math`, `decimal_point`,
  `trailing_zeros_dropped`, `latex_fraction`), so a task whose reference previously failed
  its baseline may now be measurable. That means a taskset can move from "not measured" to
  a real score. Measured on real environments, findings are unchanged.

## Added

- **`bohrin.relations` — a certified catalogue of meaning-preserving rewritings.** A
  metamorphic relation says how a verdict must change, or must not change, when the input
  is transformed in a known way — the standard answer to the oracle problem, and what
  Bohrin was already doing informally without saying so.

  Every relation now carries a **certification**: one sentence giving the reason its
  rewriting preserves meaning *by construction*. And every relation is **partial** — one
  that does not apply returns nothing rather than guessing. That partiality is the
  soundness mechanism. A relation that over-claims would let Bohrin report a verifier for
  rejecting an answer that was never equivalent to begin with, which is a false accusation
  reached from the other direction.

  The four new relations were picked from measured evidence. Across 307,420 verdicts on
  four widely-used verifiers, self-validation — a verifier accepting certified-equivalent
  renderings of **its own ground truth** — ranges from **53.8% to 95.2%**, and
  whitespace and punctuation alone account for **93.0%** of in-contract failures on one of
  them. Presentational rewritings are therefore tried first, because those are what
  verifiers actually reject.

  A thousands separator is deliberately **not** included: the comma is a decimal separator
  in much of the world, so that rewriting is only meaning-preserving under an assumption
  about locale, and a certification may not contain an assumption.

- **A `bohrin.relations` entry-point group.** Relations are discovered exactly like probes,
  adapters and operators, with no privileged path for the built-ins — so a domain's own
  notation or a house answer format is a package you publish, not a patch. Built-in
  ordering lives in code rather than in the entry-point table, so installing a plugin
  cannot reorder an existing audit's baseline search.

## Verified

- `ruff check` · `ruff format --check` · `mypy --strict` · `pytest` — clean, **136 tests**,
  on Python 3.11, 3.12 and 3.13.
- **A real bug caught by testing rather than review.** `Decimal("70.0").normalize()` is
  `7E+1`, so the first implementation of `trailing_zeros_dropped` submitted `"7E+1"` —
  numerically equal, but a *different* rewriting from the one certified, meaning a
  rejection would have been reported against a promise never made. Fixed-point formatting
  keeps the claim; a test pins it and was confirmed load-bearing by reintroducing the bug.
- **No regression on real environments** (upstream `verifiers`, cloned fresh):
  `scratchpad` 50, `deepwiki` 25, `glossary` 0, `proposer_solver` 0, `alphabet_sort` 0,
  `wordle` 0 — all unchanged, and each audit still completes in seconds.

## Links

- Full changelog entry: [CHANGELOG.md → Unreleased](../../CHANGELOG.md)
