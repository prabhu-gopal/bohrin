# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

For the narrative, user-facing version of each release — with upgrade impact and context —
see [`docs/releases/`](docs/releases/). The entries below are the terse canonical record.

## [Unreleased]

### Added

- **The Coverage Score.** `scoring.coverage.coverage_score` says what fraction of the ways a
  task can be passed without doing it a grader caught, 0–100, computed per task and category.
  Each operator now declares one of five published categories, versioned as battery `1`. A
  category is caught on a task only if every grounded candidate in it was rejected, leads never
  count, a result with no grounded attempts is `not measured` rather than 100, and every score
  carries its sample, a Wilson 95% interval, and the categories it covered.

