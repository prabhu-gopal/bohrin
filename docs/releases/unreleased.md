---
title: "Bohrin — unreleased"
version: "unreleased"
date: "unreleased"
breaking: false
summary: >
  A correctness and usability release. Bohrin could report a correct verifier as
  exploited on the commonest task shape in the ecosystem; it no longer can. `bohrin audit`
  can now gate a CI job, a taskset that fails to load is a message rather than a stack
  trace, findings are grouped by root cause, and a clean score says what it does not
  prove.
---

## TL;DR

**If you audit tasksets whose answers are numbers, booleans, or empty collections,
re-run them.** Bohrin could report a Verification Gap against a verifier that was
working perfectly. That is fixed, along with two narrower paths to the same fault.

`bohrin audit` can now **fail a CI job**: `--fail-on-finding` or `--fail-on-gap SCORE`,
with a documented exit-code contract. Gating is opt-in, so nothing already scripting
`bohrin audit` changes behaviour.

Two things that made reports harder to trust than they should have been are fixed: a
taskset that fails to load now produces a message instead of a Python traceback, and a
clean `0 / 100` now states what a clean result actually bounds. `pyyaml` — declared but never imported — is
removed, several docs that had drifted from the code are corrected, and this folder
(per-release notes for the website) is introduced.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** **re-run any audit whose findings you acted on**, if the taskset's
  answers are numbers, booleans, `None`, or empty collections. Some `constant_return`
  findings from 1.0.1 were not real, and a Verification Gap computed from them was too
  high. Findings from `empty_body`, `identity_return` and `refusal` are unaffected.
- **New minimums:** none
- **`bohrin explain <unknown-probe>` now exits 2 instead of 1.** It is bad input, and 2 is
  what every other bad input returns; 1 now means "a gate was set and the audit is over
  it". If you script `explain`, check for non-zero rather than exactly 1.
- **Exit codes are now a contract**, printed in `bohrin --help`: `0` clean or gate passed,
  `1` over the gate, `2` bad input or taskset failed to load, `3` a gate was set but
  coverage was incomplete. Only `1` and `3` are new, and neither can occur unless you pass
  a gate flag.
- **Scores may go down.** A gap that falls after upgrading is the fix working, not a
  regression in coverage. Findings on real public environments are unchanged.

## Added

- **A CI gate, with an exit-code contract.** `--fail-on-finding` exits 1 on any finding;
  `--fail-on-gap SCORE` exits 1 at or above a Verification Gap. Before this, every
  completed audit returned 0 — an audit reporting 20 exploits at a gap of 50 was
  indistinguishable from a clean one, and the only workaround was grepping stdout.

  Gating is opt-in, matching `semgrep scan` and `trivy`. **Exit 3 is the part that is
  ours.** A gate can pass because nothing was *found*, or because nothing was *measured*,
  and those are different claims — Trivy's documented trap is exactly a pipeline that
  merges happily because a flag was missing. So a gap that could not be computed, or
  coverage short of the full probe set, exits 3 rather than being folded into pass or
  fail, letting a pipeline treat *we could not tell* differently from *it is clean*. This
  is the distinction SARIF draws with `invocation.executionSuccessful`. Confirmed against
  a real environment: `code_golf`, whose tasks all need a runtime, exits 3 rather than
  reporting a false green.

- **`docs/releases/`** — one Markdown file per released version, written for
  people who use Bohrin, feeding the website's changelog page. See
  [`docs/releases/README.md`](./README.md) for the format and the process.

## Changed

- **Findings are grouped by the operator that produced them.** One operator landing on 20
  tasks is one defect with one fix, and the report used to print it 20 times — six full
  blocks then "14 more findings". That pushed any *second*, different defect off the
  screen behind the first one's repetitions. Auditing `scratchpad` now reports
  `identity_return accepted on 20 tasks` once, with a worked example and its reproduction
  command, and the whole audit fits on one screen. A single-task finding reads exactly as
  it did, and two distinct operators are never merged into one.

- **A Verification Gap of 0 now says what it does not prove.** Bohrin reports only defects
  its operators can construct a payload for, so a clean result is a lower bound: absence
  of findings is absence of evidence, not evidence of absence. Two environments in this
  project's own sweep score 0 and are still exploitable — `glossary` grades by substring
  containment, `proposer_solver` by the last integer in a reply — because no model-free
  operator here builds those payloads. That limit was documented in
  `docs/05_ROBUSTNESS.md` and absent from the report, which is what people actually read.
  A clean score now carries a line naming how many operators were tried and what a clean
  result bounds. A false reassurance is a false accusation pointed the other way.

- **`--no-color` is accepted after the subcommand.** `bohrin audit ./env --no-color` is
  what people type, and it used to fail with `unrecognized arguments`.

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

- **A taskset that fails to load is a message, not a traceback.** Loading a taskset
  imports your package and runs its module-level code, so it can raise anything — but only
  `ModuleNotFoundError` was handled. Everything else escaped as a raw Python stack trace.
  This is not an edge case: it was hit on the first attempt with a taskset written against
  a slightly different `verifiers` API, and `verifiers` is pre-1.0, so version drift is
  normal. A stack trace reads as *Bohrin crashed* when the truth is *your taskset did not
  load*. You now get the taskset name, the underlying error, a statement that the fault is
  not Bohrin's, and exit 2.

- **Documentation now matches the code** (#23). `execute/runner.py` claimed a
  Python 3.10 floor (it is 3.11) and pinned the `gather`-over-`TaskGroup` choice
  on that; the real reason — `TaskGroup` cancels every sibling when one task
  raises, which would abandon an audit over a single hung verifier — is now in
  the docstring. `docs/01_ARCHITECTURE.md` referenced two report modules that do
  not exist and showed core types that had drifted from `ir/task.py`.
  `docs/03_PROBES.md` listed seven mutation operators, two of which
  (`off_by_one`, `swap_operator`) are deliberately unregistered, and omitted
  `refusal`, which ships. `CONTRIBUTING.md` named Python 3.10 as supported.

## Verified

- `ruff check` · `ruff format --check` · `mypy --strict` · `pytest` (124 passed) — clean.
- **Measured cold against real data.** Upstream `verifiers` cloned fresh from GitHub, a
  new venv, all 19 published environments installed. 12 measured at full coverage, 7
  refused, **two real defects found and zero false accusations**. `scratchpad` reports
  50/100; `deepwiki` reports 25/100 — a defect found during this work and confirmed
  independently with Bohrin out of the loop: its reward is
  `answer.lower() in reply.lower()` with `answer="python"`, and the prompt names the repo
  `modelcontextprotocol/python-sdk`, so echoing the prompt scores full marks without ever
  calling the tool the task exists to exercise.
- **The gate verified end to end on real environments**: no flag → 0 even with findings;
  `--fail-on-finding` on `scratchpad` → 1; `--fail-on-gap 40` (gap 50) → 1;
  `--fail-on-gap 60` → 0; a clean `glossary` → 0; unmeasurable `code_golf` → 3; a taskset
  that fails to load → 2.
- **Every new guard was verified by removing it** and confirming the suite went red.

## Links

- Full changelog entry: [CHANGELOG.md → Unreleased](../../CHANGELOG.md)
- PRs: #23, #25, #26, #27, #28
