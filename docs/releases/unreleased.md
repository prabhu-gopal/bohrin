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

- **`false_negation` — a new mutation operator that finds a whole grader shape Bohrin
  previously walked past.** It submits an explicit denial of the taskset's own declared
  answer: `The answer is not 70.` where the taskset says the answer is `70`. Its wrongness
  comes from the taskset's ground truth, not from the verifier being audited.

  A verifier that decides by asking whether the answer appears *somewhere in the reply*
  cannot tell an assertion from its denial — the denial contains the answer too. That is
  one of the commonest grader shapes in the ecosystem, and nothing in the previous operator
  set constructed a payload for it.

  **Findings on the public `verifiers` corpus go from two environments to four.**
  `glossary` and `color_codeword` move from 0/100 to 50/100; `deepwiki` from 25 to 50. If
  you audited a taskset that grades by containment or by extracting a value from free text,
  **re-run it** — a clean result from before may not survive.

  Both new findings were confirmed independently with Bohrin out of the loop. `glossary`
  grades `answer.lower() in reply.lower()`, so a reply denying the answer scores full
  marks. `color_codeword` extracts the longest standalone A–I run and compares it exactly,
  so `The answer is not ABC.` yields `ABC` and scores full marks. In both, a reply that
  explicitly says the answer is wrong is rewarded as if it were right.

## Fixed

- **A task id with a space broke the reproduction command.** Task ids come from the
  taskset and often contain spaces — `glossary` names its tasks after people — so
  `--task Ada Lovelace` split into two arguments and the printed command failed with
  `unrecognized arguments: Lovelace`. Evidence you cannot re-run is the worst defect a tool
  like this can have. Task ids and operator names are now shell-quoted, and a test parses
  the printed command back through the argument parser.


- **A taskset with no reward function was reported as clean.** If a task carries no reward
  hook there is no verifier to audit: everything submitted scores zero, everything is
  "rejected", nothing is ever a finding — and the audit came back `0 / 100` at
  `coverage: 2 of 2 probes`. The strongest statement Bohrin can make, from measuring
  nothing, and a `--fail-on-gap` job went green on it.

  **Five of the eighteen loadable public `verifiers` environments do exactly this** —
  `wordle`, `kuhn_poker`, `openenv_wordle`, `proposer_solver`, `wiki_search` — because they
  are judged cross-agent, per episode, or by a seat minted once a model has run. All five
  reported clean.

  Both probes now refuse those tasks and name the reason. They report
  `not measured · coverage: 0 of 2 probes`, and a CI gate exits 3 instead of 0. If you
  audited one of these, **its clean result was never a result**; re-run it.

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
