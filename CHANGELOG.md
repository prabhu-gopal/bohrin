# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The **report schema** is versioned separately from the package — see `schema_version` in
any `--json` output. It changes only when the serialized report shape changes.

## [Unreleased]

### Added

- Design documentation for the open core in `docs/`: architecture, the Verification Gap
  specification, the two open probe designs, and the open/proprietary boundary.
- The probe framework, the `weak_oracle` and `determinism` probes, the baseline mutation
  operators, the Verification Gap with its mandatory coverage descriptor, and the
  `audit` / `list-probes` / `explain` command surface.

- **`weak_oracle` now requires a green baseline.** Where a task ships a reference
  solution it is submitted unchanged first and must pass. Mutation testing assumes the
  unmutated code passes; without that, an accepted mutant cannot be distinguished from
  Bohrin submitting in a form the verifier does not understand — and reporting the former
  when the latter is true blames a customer for our own bug. Tasks that fail their
  baseline are excluded from the score and reported; if none can be baselined the probe
  reports `error` rather than `ok`.
- **`determinism` now reports the statistical power of its own measurement.** A null
  result bounds the flake rate rather than establishing determinism: at five repeats a
  verifier that flips 5% of the time is missed roughly 77% of the time. The terminal
  headline reads "no variance observed in 5 runs" instead of implying a conclusion.

### Changed

- **Python 3.11 is the supported floor**, down from 3.10 in the previous project. Two
  independent reasons: `verifiers`, the only adapter target at launch, requires
  `>=3.11,<3.14`; and Python 3.10 reaches end of life on 31 October 2026. The CI matrix
  and branch protection were updated to match — required checks went from nine to seven,
  and leaving the 3.10 names in place would have blocked every future merge.

### Changed

- **This project is now a verifier auditor, not a dataset analyzer.** The previous tool —
  static analysis for robot demonstration data — was renamed and is published as
  [`adduct`](https://pypi.org/project/adduct/), with its full history in that repository.
  The `bohrin` name now belongs to this project. Releases 0.1.0 and 0.2.0 on PyPI are
  yanked and point users at `adduct`; the first release of the verifier auditor will be
  1.0.0, so that the discontinuity reads as a break rather than an upgrade.

[Unreleased]: https://github.com/prabhu-gopal/bohrin/compare/v0.2.0...HEAD
