---
title: "Bohrin — unreleased"
version: "unreleased"
date: "unreleased"
breaking: false
summary: >
  A correctness release. Bohrin could report a correct verifier as exploited on the
  commonest task shape in the ecosystem; it no longer can, and the guard is enforced by
  fixtures that model verifiers which are lenient about presentation and still right.
---

## TL;DR

**If you audit tasksets whose answers are numbers, booleans, or empty collections,
re-run them.** Bohrin could report a Verification Gap against a verifier that was
working perfectly. That is fixed, along with two narrower paths to the same fault.

Nothing else in how Bohrin runs changes. `pyyaml` — declared but never imported — is
removed, several docs that had drifted from the code are corrected, and this folder
(per-release notes for the website) is introduced.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** **re-run any audit whose findings you acted on**, if the taskset's
  answers are numbers, booleans, `None`, or empty collections. Some `constant_return`
  findings from 1.0.1 were not real, and a Verification Gap computed from them was too
  high. Findings from `empty_body`, `identity_return` and `refusal` are unaffected.
- **New minimums:** none
- **Scores may go down.** A gap that falls after upgrading is the fix working, not a
  regression in coverage. Findings on real public environments are unchanged.

## Changed

- **`pyyaml` is no longer a declared dependency** (#23). It was listed for a
  `bohrin.yaml` config file that was never built, so nothing in `src/bohrin/`
  imported it — which broke this project's own rule that every declared
  dependency is imported by a line of code. `types-PyYAML` is dropped from the
  dev extra for the same reason. A per-project config file can reintroduce it
  when a user asks. `pyyaml` still resolves transitively through the `verifiers`
  extra, so nothing at runtime changes.

## Fixed

- **A correct verifier could be reported as exploited.** Four paths claimed a wrongness
  ground from a difference in *source* rather than a difference in *behaviour*:

  | Path | Trigger |
  |---|---|
  | `constant_return` | reference `"1.0"`, a correct numeric grader, candidate `"1"` |
  | `constant_return` | reference `"true"`, a correct case-folding grader, candidate `"True"` |
  | `negate_condition` | a branch whose two arms do the same thing |
  | `drop_side_effect` | a reference whose function bodies were already `pass` |

  `"1"` and `"1.0"` are different strings and the same answer. A verifier that accepts
  the first for the second is doing numeric comparison, which is correct — and Bohrin
  was calling it broken, at a Verification Gap of 50/100.

  The new `bohrin.mutate.equivalence` module refuses a ground unless the payloads differ
  under every normalisation a correct verifier might apply, and adds Trivial Compiler
  Equivalence on Python bytecode so a mutant that compiles to its own reference can never
  be an exploit. `negate_condition` now carries no ground and produces leads only.

  The clean fixture was an exact-string matcher — it models a *strict* verifier, so it
  could not express this failure at all. The suite now runs every operator against a
  table of graders that are lenient about presentation and still entirely correct.

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

- `ruff check` · `ruff format --check` · `mypy --strict` · `pytest` (104 passed)
  · `uv build` · `bohrin` CLI surface (`--version`, `list-probes`, `explain`, a
  bad-path error) — all clean.

## Links

- Full changelog entry: [CHANGELOG.md → Unreleased](../../CHANGELOG.md)
- PRs: #23, #25
