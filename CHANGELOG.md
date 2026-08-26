# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The **report schema** is versioned separately from the package — see `schema_version` in
any `--json` output. It changes only when the serialized report shape changes.

## [Unreleased]

### Added

- **`benchmarks/` — published measured evidence on real public data.** The first run,
  `benchmarks/2026-08-26-lerobot-20-v0.1.0/`, scans 20 curated public LeRobot datasets
  (4,342 episodes, 545,964 frames, 2–40 action dims, 5–50 Hz, sim and real, 14 of them
  Open X-Embodiment conversions): 20/20 parsed without error in 22.3 s on a laptop CPU,
  producing 189 findings (23 HIGH, 121 MEDIUM, 45 LOW). Of the 46 default detectors, 27
  fired at least once, 19 never fired, and only 4 ever reached HIGH. Ships the raw sweep
  JSON for both the uncapped and the default triage pass, a report, the sweep and figure
  scripts, and a LaTeX paper. The unit suite measures recall on synthetic fixtures; this
  measures how often detectors complain about healthy real data, which the suite cannot.
- **Measured: the default 300-episode triage cap does not change the conclusions** on this
  corpus. Comparing a capped scan against one that reads every episode, all 23 HIGH
  findings are identical, as are the counts of detectors that fired and detectors reaching
  HIGH; 2 MEDIUM findings out of 189 differ, on the 3 datasets that the cap subsamples.

### Fixed

- **Scans no longer leak numerical warnings to stderr.** `LinAlgWarning: Ill-conditioned
  matrix` and numpy `divide by zero` / `overflow` / `invalid value` warnings from
  scikit-learn could appear during an ordinary `bohrin scan`. The ill-conditioning had a
  real cause: the dynamics fits stack consecutive states, which are collinear by
  construction, under a ridge penalty of 1e-6 that left that collinearity essentially
  unregularized. Features are now standardized per fold and the penalty is 1.0, and the
  solve **abstains** rather than returning a residual from a fit LAPACK flags as
  unreliable. The remaining warnings are IEEE flags raised inside BLAS during clustering,
  on input already validated as finite; they are suppressed at one documented boundary in
  the engine, with `BOHRIN_SHOW_NUMERIC_WARNINGS=1` to restore them for debugging. Genuine
  non-finite data is still reported by `integrity.nan_inf`. Measured across the 20-dataset
  benchmark: 42 warning lines before, 0 after.

### Changed

- **`dynamics.inverse_residual` no longer runs in a default scan.** Measured on the
  20-dataset benchmark: it fires on **100%** of the corpus (20/20) and reports HIGH on 50%
  (10/20), and reaches the report's visible top-5 on 60% of datasets, more often than either
  detector already excluded. Its HIGH rate is lower than theirs; the 100% fire rate is what
  decides it, because a detector that fires on every curated public dataset cannot
  discriminate whatever severity it attaches. Excluding it takes the corpus from 23 HIGH
  findings to 13 and the datasets carrying at least one HIGH from 17 of 20 to 11 of 20.
  Nothing is deleted: it stays fully implemented and reachable with `--all`. One explanation
  was tested and rejected first (see Fixed, below); the two that survive are confounded in
  that corpus, so recalibration waits on a corpus of natively-recorded community datasets.
  `dynamics.forward_residual` is the next candidate and is deliberately **not** excluded
  yet: it has the highest top-5 visibility of any detector (75%) but never reports HIGH.
- **A default `bohrin scan` now details the top 5 findings instead of 6**, and names the
  flag that carries the rest (`--html` or `--json`, never `--all`, which adds the
  held-back over-reporting detectors). The benchmark measured a median of 9.5 findings per
  dataset with no dataset ever coming back clean; at that density the terminal is a triage
  surface, not the full record. Nothing is dropped from any machine-readable output.
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

- **Six detectors are effectively always-on** and their thresholds are not yet trustworthy.
  Measured across the 20-dataset benchmark: `dynamics.inverse_residual` 100%,
  `dynamics.forward_residual` 90%, `smoothness.jerk_outlier` 85%, `smoothness.curvature`
  75%, `smoothness.path_efficiency` 70%, `temporal.non_markovian_pause` 70%. A detector
  firing on 85% of curated public data carries almost no information whatever severity it
  attaches, and these six are the bulk of a report's length. Recalibration needs a corpus
  that represents the intended user, which the current one does not (see below).
- **`dynamics.inverse_residual`'s HIGH severity is not yet trustworthy** (HIGH on 50% of
  the benchmark). One hypothesis was tested and rejected: fixing the ill-conditioned ridge
  solve eliminated the numerical fault but left the fire rate and HIGH rate unchanged. The
  two surviving explanations, control rate and format-conversion provenance, are perfectly
  confounded in that corpus and cannot be separated there. See
  `benchmarks/2026-08-26-lerobot-20-v0.1.0/REPORT.md` §6.
- **The benchmark corpus is not the population bohrin is for.** 14 of its 20 datasets are
  Open X-Embodiment conversions at 5 Hz, against an intended user recording natively at
  30 Hz. The HIGH rate is 64% on the former and 17% on the latter, so a share of those
  findings may reflect format conversion rather than data quality.
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
