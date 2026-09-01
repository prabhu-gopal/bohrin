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

### Changed

- **This project is now a verifier auditor, not a dataset analyzer.** The previous tool —
  static analysis for robot demonstration data — was renamed and is published as
  [`adduct`](https://pypi.org/project/adduct/), with its full history in that repository.
  The `bohrin` name now belongs to this project. Releases 0.1.0 and 0.2.0 on PyPI are
  yanked and point users at `adduct`; the first release of the verifier auditor will be
  1.0.0, so that the discontinuity reads as a break rather than an upgrade.

[Unreleased]: https://github.com/prabhu-gopal/bohrin/compare/v0.2.0...HEAD
