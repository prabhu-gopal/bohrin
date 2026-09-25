# Architecture

A map of the code for someone about to change it. It says where things are and which rules
the code keeps that you cannot see by reading any one file. How each module works is in its own
docstrings; what the concepts mean is in [docs/concepts.md](docs/concepts.md).

## Bird's eye view

Bohrin is a library that **generates, checks and scores**. Given a task, it builds the
submissions a correct grader must reject (the *battery*), with the proof that each one is wrong.
Given which of those submissions a grader accepted, it computes the Coverage Score and the
Verification Gap. It also publishes the standard those things are defined by, as data: the
weakness list, the probe manifests and the finding schema.

It never runs a grader. Something else (your own loop, a CI job, another tool) runs the grader
and passes the verdicts back.

```
Task ──► operators ──► battery rules ──► Candidates ──► [your grader] ──► Attempts ──► scoring
          (mutate)       (mutate)          (ir)                             (scoring)   (scoring)
                                                                    Findings ◄── evidence
```

## Codemap

`src/bohrin/` is the package. Everything public is typed (`py.typed`) and checked with
`mypy --strict`.

- **`ir/`**: the shared vocabulary every other module is written against.
  - `task.py`: `Task`, `Shape`, the two submission types `Source` and `Workspace`, and
    `Candidate` (a submission plus its `Ground` and `Provenance`). `Workspace` holds the rules
    that keep a template a template.
  - `result.py`, `evidence.py`: what a check produces (`ProbeResult`, `Exploit`, `Flake`, and
    the rest), consumed by the scoring.
- **`mutate/`**: builds the battery.
  - `base.py`: `MutationOperator`, the contract every operator follows, built-in or third-party.
  - `operators.py`: the built-in operators.
  - `battery.py`: `battery()`. Runs the operators for a task's shape, then applies the rules that
    stop a false accusation. **If you change what counts as wrong, it is here.**
  - `equivalence.py`: decides when two submissions are really the same (the normalisation ladder
    and Trivial Compiler Equivalence). Every function here can only remove a ground.
- **`relations/`**: positive controls, correct work a grader must accept. `positive_controls(task)`
  gives the reference (the baseline) and every certified rewriting of it; `builtin.py` holds the
  rewritings (comment-free, reformatted, renamed locals) and `certify.py` the mechanical proofs
  (same syntax tree; same bytecode up to local names). Third parties add rewritings through the
  `bohrin.relations` entry point.
- **`scoring/`**: `coverage.py` (the Coverage Score, `BATTERY_VERSION`, `CATEGORIES`),
  `scorecard.py` (correct-work acceptance beside it, per grader shape then overall, with the tasks
  left out and why), `gap.py` (the Verification Gap), `interval.py` (Wilson intervals).
- **`conformance/`**: the conformance suite's expected results (`bcl-1.toml`), the results format
  (`conformance-results.v1.json`) and `check()`, which compares a tool's results with them. The
  fixture graders themselves live outside the package, in `conformance/` at the repository root:
  they run submissions, and the library never does.
- **`spec/`**: the standard as data.
  - `weaknesses.toml` and `weaknesses.py`: the weakness list and its loader.
  - `probes.toml` and `probes.py`: the probe manifests and their loader.
  - `ids.py`: the identifier formats (`BGW-`, `BVR-`, probe IDs, `BF-`, schemas, `BCL-`).
  - `python -m bohrin.spec` regenerates `docs/WEAKNESSES.md`.
- **`evidence/`**: the finding record (`finding.py`) and its published JSON Schema
  (`finding.v1.json`), with `finding_id()`; and the reproduction-script contract
  (`reproduction.py`, `reproduction-result.v1.json`): the static check of a script, the reading
  of its result, and invariant I7, a finding whose script does not reproduce it loses its proof.
  `docs/examples/` holds a complete script that the tests run.
- **`stats/`**: `bohrin power`. `estimates.py` (standard errors, clustered and paired, and the
  minimum detectable difference, each tied to its published equation), `results.py` (the results
  file format and its strict reader, with `results-row.v1.json`), and `power.py` (the analysis,
  the aggregation audit, the report and `power-report.v1.json`).
- **`history/`**: `bohrin verify`. `git.py` (the one module that starts a process: read-only
  git, safe in a hostile repository), `facts.py` (the rules, on syntax trees), `oracle.py` (how
  strongly a test checks, and how a change can weaken it), and `verify.py` (the report and
  `verify-report.v1.json`).
- **`report/`**: renderers. `sarif.py` writes `verify`'s facts as SARIF 2.1.0 for code-scanning
  annotations; rule descriptions come from `history/rules.py`, the one table of what each rule
  means, which a test holds to the rules the code emits and to docs/SPEC.md.
- **`action.yml`** (repository root): the GitHub Action that runs `bohrin verify` on a pull request
  and uploads the SARIF. Inputs reach its shell only through environment variables.
- **`cli.py`**: the `bohrin` command (also `python -m bohrin`), with the exit codes every verb
  shares.
- **`_plugins.py`**: entry-point discovery, shared by operators and relations.

`tests/` mirrors the package. `tests/_fixtures.py` holds graders with known behaviour, correct and
weak; most tests are "no correct grader is accused, and a weak one is still caught".

`docs/` holds the public documentation; see [docs/README.md](docs/README.md).

## Invariants

These hold everywhere. Several are rules about what the code must *not* do, which is why they
are written down here.

1. **The library never calls a grader.** No module imports a runner or opens a network
   connection, and only one starts a process: `history/git.py`, which runs read-only git
   plumbing (`rev-parse`, `merge-base`, `ls-tree`, `cat-file`, `ls-files`, `log`) with every
   repository-named program switched off. It never diffs the working tree, because that runs a
   repository's filters whatever is switched off. `tests/test_boundaries.py` pins all of this.
2. **A submission is called wrong only on a ground established without the grader.** A candidate
   with `ground=None` is a lead and is never counted in a score.
3. **Every rule after generation can only remove a ground.** `battery()` and `equivalence.py` may
   drop a candidate or withdraw its ground. Nothing may add one.
4. **Templates are never instantiated.** A `Workspace` path may name a declared parameter such as
   `{test_root}`. No code fills one in.
5. **Every guard has a test that fails without it.** When you add a rule that prevents a false
   accusation, delete it, watch a test fail, and put it back.
6. **Identifiers are permanent.** A `BGW-` ID is never removed, renamed or reused
   (`tests/test_weaknesses.py` pins them). A `BF-` ID is derived only from stable inputs, and a
   test vector pins how.
7. **Data and code agree.** Each operator emits exactly what its manifest promises, each category
   is a weakness family, and the finding schema refuses exactly what the code refuses. Tests hold
   each pair together.
8. **Every number carries its sample, its interval and the battery version.** A score over
   nothing is "not measured", never 100.

## Boundaries

- **Entry points are the public seams**, and their group names are public API: `bohrin.mutators`
  (operators) and `bohrin.relations` (rewritings). Built-in and third-party code use the same
  route; nothing is privileged.
- **The data files are public formats**: `weaknesses.toml`, `probes.toml` and `finding.v1.json`
  are read by tools that never import Bohrin. Change them additively.
- **Runtime dependencies are only the standard library and `libcst`.** A dependency is declared
  only when a line of code imports it; test-only tools live in the `dev` extra.

## Cross-cutting concerns

- **Versioning.** `BATTERY_VERSION` changes whenever a category is added, removed or redefined.
  Probe IDs carry a major version. Schemas are versioned in their URI.
- **Testing.** CI runs `ruff`, `ruff format --check`, `mypy --strict` and `pytest` on Python 3.11,
  3.12 and 3.13, on Linux and macOS, and installs the built wheel into a clean environment.
- **Wording.** Findings, docs and code comments describe how a grader fails, never whose. A
  third party's grader is never named as defective in this repository.
