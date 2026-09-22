# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
