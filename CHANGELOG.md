# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The **report schema** is versioned separately from the package — see `schema_version` in
any `--json` output. It changes only when the serialized report shape changes.

## [Unreleased]

### Added

- **`benchmarks/` — published measured evidence on real public data.** The first run,
  `benchmarks/2026-08-26-hub-sweep-v0.1.0/`, scans 20 curated public LeRobot datasets
  (2,631 episodes, 545,964 frames, 2–40 action dims, 5–50 Hz, sim and real): 20/20 parsed
  without error in 20.8 s total on a laptop CPU, producing 187 findings (23 HIGH, 119
  MEDIUM, 45 LOW). Of the 46 default detectors, 27 fired at least once, 19 never fired,
  and only 4 ever reached HIGH. Ships the raw `sweep.json`, a report, the figure-generation
  script, and a LaTeX paper. The unit suite measures recall on synthetic fixtures; this
  measures how often detectors complain about healthy real data, which the suite cannot.

### Changed

- `smoothness.discontinuity_jump` and `integrity.declared_mismatch` (see "Known
  limitations" under 0.1.0) no longer run in a default scan. Measured on the same
  20-dataset sweep: when either fired, the report's own ranking (severity × blast radius)
  put it in the visible top-6 findings 13 of 16 times, winning the #1 or #2 slot in 6 of
  those — a first-time user's first impression was disproportionately likely to be one of
  the two things already known to probably be wrong. Nothing is deleted, degraded, or
  hidden: both are fully implemented and reachable with the new `--all` flag
  (`bohrin.scan(..., all_detectors=True)` in the Python API), and this default list lives
  at `bohrin.detectors.registry.DEFAULT_EXCLUDED`.

### Known limitations

- **`dynamics.inverse_residual`'s HIGH severity is not yet trustworthy.** On the 20-dataset
  sweep it fires on 95% of datasets and reports HIGH on 50%. A HIGH that fires on half of
  a curated, published corpus is more likely to be a threshold defect than an epidemic. No
  ground-truth adjudication has been done, so this is not yet grounds for excluding it —
  it is grounds for not trusting the severity. See
  `benchmarks/2026-08-26-hub-sweep-v0.1.0/REPORT.md` §4.2.
- **`--fpr` is inert out of the box, and public metadata makes it hard to fix.** The
  conformal gate needs a calibration corpus keyed by embodiment (Mondrian), and none ships
  with the package. The sweep also found that 18 of 20 public LeRobot datasets declare
  `robot_type: "unknown"`, so an embodiment-keyed taxonomy built from Hub metadata
  collapses to the single wildcard bucket and forfeits group-conditional validity.

## [0.1.0] — unreleased

First public release.

### Added

- `bohrin scan <path>` — analyze a robot-learning dataset and report the defects that hurt
  training, with severity, affected episodes, the measured value, the mechanism, and a fix.
- **Hugging Face Hub support**: `bohrin scan lerobot/pusht` fetches `meta/` and `data/`
  (never video) and scans the local snapshot. This is the only network call in the tool.
- **Formats**: LeRobot v2.1 and v3.0 (autodetected), RLDS/Open-X, robomimic and raw HDF5,
  Zarr replay buffers, NumPy directories.
- **Machine-readable output**: `--json` (versioned `schema_version`), `--sarif` (SARIF
  2.1.0 for GitHub code scanning), and a self-contained `--html` report.
- **CI gating**: `--ci --fail-on <severity>` exits non-zero only when you ask it to.
- **Calibration**: `bohrin calibrate` builds a conformal FDR corpus from your own
  known-good data, after which `--fpr` governs the covered detector gates.
- `bohrin list-detectors`, `bohrin explain <detector-id>`, and `bohrin init`.
- Adapters and detectors are plugins discovered through entry points — the same mechanism
  the built-ins use.

### Fixed

- `dynamics.inverse_residual` reported HIGH unconditionally, whatever the measured extent.
  Across 20 curated public LeRobot datasets it fired at HIGH on 19 of them, with flagged
  fractions spanning 0.94% to 80.8% all reported identically. Severity now scales on extent
  (≥20% of transitions) **or** magnitude (a residual as large as the signal itself, which is
  physically unexplainable however rare). HIGH rate on real data: 95% → 50%,
  measured with `scripts/hub_smoke.py`.
- A clean scan printed "No findings" twice.

### Known limitations

- `smoothness.discontinuity_jump` and `integrity.declared_mismatch` report HIGH on 70% and
  60% of curated public datasets respectively, which is far more likely to be a threshold
  problem than a real epidemic. Documented in the README rather than silently shipped as
  trustworthy; re-tuning them needs data we do not have yet.

### Deliberately not included

- **No 0-100 health score.** An aggregate number implies a calibration against real
  training outcomes that does not exist yet — nothing here measures how much each defect
  actually costs a trained policy. The report gives severity counts and ranked findings,
  every one of which is individually defensible. The scoring function
  (`bohrin.synth.pipeline.quality_score`) is still present and tested; the headline
  returns when a corpus of training runs can back it.

### Notes

- Python 3.10 through 3.13 are supported and tested.
- No telemetry. Your data never leaves your machine.
- `schema_version` is `1.0` — the first published report contract. Nothing consumed an
  earlier shape, since no version of bohrin was ever released.

[Unreleased]: https://github.com/prabhu-gopal/bohrin/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/prabhu-gopal/bohrin/releases/tag/v0.1.0
