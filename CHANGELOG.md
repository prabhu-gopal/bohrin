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
- **`bohrin.ir.task.Shape`**: the ways a grader is called — `program`, `io`, `workspace`,
  `container`, `history`, and `numeric`, `proof` and `query`.
- **The specification defines every check behind the Verification Gap.** `docs/SPEC.md` now
  states what `weak_oracle`, `determinism`, `ground_truth_rejected` and `answer_leakage` ask,
  how each sub-score is computed, why two of them carry weight 0, and the three result states,
  so a Verification Gap can be recomputed and argued with from the specification alone.
- **`CITATION.cff`**, so the project can be cited from GitHub's "Cite this repository" button
  or any reference manager. A test keeps its version in step with the package.

### Changed

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
