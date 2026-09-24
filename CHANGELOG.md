# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **The weakness list** (`docs/WEAKNESSES.md`, `bohrin.spec`): 38 classes, `BGW-101` to
  `BGW-138`, covering every published way a coding grader or its harness can be cheated or be
  wrong — hollow programs, harness tampering, answer access, weak or wrong tests, grader logic,
  isolation and measurement adequacy. Each class has a mechanism, the grader shapes it applies
  to, the evidence a finding of it carries, fix guidance and public sources, and the list is
  crosswalked to two published taxonomies (an 11-category exploit dataset and an 11-item task
  rubric). It ships as data, `src/bohrin/spec/weaknesses.toml`, which any tool can read without
  importing Bohrin.
- **Identifier formats** (`bohrin.spec.ids`, and "Identifiers" in `docs/SPEC.md`) for weakness
  classes (`BGW-`), registry records (`BVR-`), probes (`bohrin/<slug>@<major>`), findings
  (`BF-`), schemas and conformance levels.
- **Reproduction scripts** (`bohrin.evidence.reproduction`, the result schema
  `https://bohrin.com/schema/reproduction-result/v1`, and "Reproduction scripts" in
  `docs/SPEC.md`). Every proven finding's script is a standalone PEP 723 script: it needs nothing
  from Bohrin and makes no network call. It checks its embedded submission against the declared
  digest, and runs the reference and the submission at least three times each. It reports one of
  `reproduced`, `not-reproduced`, `flaky`, `baseline-failed` or `error`, with a distinct exit
  code. `check_script()` checks a script without running it. `parse_result()` recomputes the
  outcome from the recorded runs rather than trusting the script. `apply()` downgrades a finding
  its script did not reproduce, and never upgrades one. A complete, runnable example is in
  `docs/examples/`.
- **Documentation for newcomers**, organised by what a reader needs:
  - a [tutorial](docs/tutorial.md) that checks a first grader step by step;
  - [concepts](docs/concepts.md), explaining the idea and every term in a glossary;
  - [ARCHITECTURE.md](ARCHITECTURE.md), with the code map and the invariants the code keeps;
  - how-to guides for [adding a probe](docs/how-to/add-a-probe.md) and
    [adding a weakness class](docs/how-to/add-a-weakness.md);
  - a [map of all the docs](docs/README.md).

  Tests run every example in the tutorial and the README against the output they show, check
  every relative link and anchor, require a docstring on every public class and function, and
  check that the package never imports a network or process module or calls `exec`.
- **The finding record** (`bohrin.evidence`, published as the JSON Schema
  `https://bohrin.com/schema/finding/v1`): six evidence levels, from `proven` to `excluded`; the
  submission recorded as digests; differentiating inputs and observations; run conditions. A
  record that claims more than its evidence supports cannot be made or read. A proven finding
  needs a ground, a paying verdict, a passing baseline and a reproduction script, and a
  differentiating observation proves nothing without the reference and at least three
  presumed-correct solutions passing it. `finding_id()` derives the same `BF-` ID for the same
  defect on every run from RFC 8785 canonical JSON, so it can be recomputed in any language, and
  `normalise_finding_id()` reads one as people type it. Reading a record is strict: every field
  must be exactly the type the schema gives it (`"false"` is not `false`; `NaN` is refused), and a
  test holds the reader and the schema to the same verdict on every single-field breakage.
- **Probe manifests** (`src/bohrin/spec/probes.toml`, `bohrin.spec.probes`): every built-in
  probe described as data a third-party tool can read without importing Bohrin: ID
  (`bohrin/empty-implementation@1`), weaknesses, shapes, template and its parameters, ground,
  expected verdict, maturity, battery, guards and sources. The loader refuses a manifest that
  names an unknown weakness, a negative control without a ground, or a template path outside
  its root, and a test ties each manifest to what its operator actually emits.
- **`bohrin.ir.task.Shape`**: the ways a grader is called — `program`, `io`, `workspace`,
  `container`, `history`, and `numeric`, `proof` and `query`.
- **Workspace submissions and task shapes.** `bohrin.ir.task.Workspace` describes file
  changes and commands as a template: a path may name a declared parameter such as
  `{test_root}`, and the library never fills one in. Paths that are absolute, contain `..`, or
  name an undeclared parameter are refused. `Task.shape` (default `program`) says how a task's
  grader is called, and `MutationOperator.shapes` says which shapes an operator applies to; the
  battery runs only the operators for a task's shape. The battery's rules reach workspaces too:
  duplicates are tried once, and a grounded workspace that writes the reference into any file
  is suppressed.
  Paths that start with a drive letter are refused too, and text that is not valid Unicode (a
  lone surrogate) is refused where it enters a submission rather than failing later inside a
  hash.
- **The specification defines every check behind the Verification Gap.** `docs/SPEC.md` now
  states what `weak_oracle`, `determinism`, `ground_truth_rejected` and `answer_leakage` ask,
  how each sub-score is computed, why two of them carry weight 0, and the three result states,
  so a Verification Gap can be recomputed and argued with from the specification alone.
- **`CITATION.cff`**, so the project can be cited from GitHub's "Cite this repository" button
  or any reference manager. A test keeps its version in step with the package.

### Changed

- **A candidate's payload is typed** (breaking): `Candidate.payload` is a `Source(text)` for
  program text or a `Workspace(files, commands, parameters)` for changes to a repository or
  container, instead of a bare string. Read program text as `candidate.payload.text`.
- **The battery is for coding graders only, and is battery 2.** Coverage Score categories are
  now the weakness-list families a correct grader must reject — `hollow_program`,
  `harness_tampering`, `answer_access`, `weak_tests` and `grader_logic` — so scores from
  battery 1 and battery 2 are not comparable. The battery currently submits into
  `hollow_program` (the reference with every function body emptied); a score states how many
  of the five categories it measured.
- **The README says what Bohrin is for, not only what it does today:** why graders need
  checking, the principles every check is held to (no accusation without proof, every number
  with its uncertainty, what was not checked said out loud, an open method), and the scope.
  The PyPI description and keywords match it.

### Fixed

- **An interface is no longer reported as paying for empty code.** On a task whose reference is
  an interface, an abstract base class or a protocol (every function body only a docstring,
  `pass`, `...` or `raise NotImplementedError`), `drop_side_effect` claimed the emptied version
  was structurally wrong. But the reference does no work either, and a correct grader of the
  interface is right to accept it. The operator now stays silent unless at least one function in
  the reference does work of its own. Found while reviewing the documentation. Before the fix, 3
  of 4 such references drew a grounded candidate (the `...` case was already caught), and none do
  after it.

- **Empty nested definitions no longer count as work.** A reference whose only content is an
  empty nested function or class drew a grounded candidate from `drop_side_effect`, although it
  does no work; a nested function that does work still counts.

### Removed

- **The answer-level operators and rewritings.** The operators `empty_body`,
  `identity_return`, `refusal`, `constant_return`, `false_negation`, `answer_enumeration` and
  `degenerate_output` scored a text reply rather than code, and `negate_condition` could only
  ever produce leads; all eight are removed with their entry points. The seventeen built-in
  answer rewritings in `bohrin.relations` are removed too. The `bohrin.mutators` and
  `bohrin.relations` entry-point groups are unchanged, and the rules that stop a correct grader
  being accused — suppression of a submission that is the reference, withdrawal of grounds on
  refusal and grader-state answers — still apply to every operator, including third-party
  ones. 0.3.0 keeps the answer-level battery for anyone who needs it.

## [0.3.0] — 2026-09-22

The first release: check the grader of an RL coding environment before you train on it.

### Added

- **The battery.** `bohrin.mutate.battery.battery(task)` returns the submissions a correct grader
  must reject for a task — an empty submission, the prompt echoed back, a refusal, constants,
  the reference with every function body emptied, a truncated or looping reply, a denial of the
  declared answer, several answers at once — each carrying the ground that makes it wrong
  without asking the grader. Submissions that cannot be shown to be wrong are leads, never
  counted.
- **Rules that stop a correct grader being accused.** A grounded submission that is the declared
  answer written another way, or code compiling to the reference's bytecode, is dropped; grounds
  are withdrawn where the declared answer is a refusal or a JSON object of grader state.
- **The Coverage Score.** `bohrin.scoring.coverage.coverage_score` says what fraction of the
  ways a task can be passed without doing it a grader caught, 0–100, per task and category, with
  its sample, a Wilson 95% interval, the categories covered and the battery version (`1`).
- **The Verification Gap** (`bohrin.scoring.gap`), with its coverage descriptor and both sides,
  and a Wilson interval on every rate (`bohrin.scoring.interval`).
- **Seventeen certified rewritings of a correct answer** (`bohrin.relations`), and public entry
  points (`bohrin.mutators`, `bohrin.relations`) for third-party operators and rewritings.

[Unreleased]: https://github.com/prabhu-gopal/bohrin/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/prabhu-gopal/bohrin/releases/tag/v0.3.0
