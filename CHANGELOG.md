# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The **report schema** is versioned separately from the package — see `schema_version` in
any `--json` output. It changes only when the serialized report shape changes.

## [Unreleased]

### Fixed

- **`--max-tasks` now actually bounds an audit, and an infinite taskset is refused rather
  than hung.** The adapter read tasks by calling `Taskset.load()`, which is the subclass
  hook that *builds* tasks; upstream applies `head`/`shuffle` views and the config-layer
  system prompt on the iteration path instead. Calling `load()` discarded both. The visible
  cost was severe: auditing `color_codeword` — an `INFINITE` taskset in the `verifiers`
  repo — ran past ten minutes with no output and growing memory, because the probes
  materialise the task list before scoring. The same run now completes in 10.5 seconds at
  full coverage. The quieter cost was worse: a taskset configured with a system prompt was
  audited without it, which is not the task the customer runs. As a backstop, a taskset
  still marked infinite after any `--max-tasks` bound is now refused with a message naming
  the flag, because hanging with no output is the worst way for an audit to fail.

### Known limitations

- **Recall on real environments is bounded by the six open operators, and that is visible
  in the numbers.** Auditing six `verifiers` v1 environments found one real defect:
  `scratchpad` scores with `self.data.word in answer` while its own prompt contains
  `word="alpha"`, so echoing the prompt back scores full marks without ever calling the
  tool — 8 of 8 tasks, gap 50/100, confirmed independently through `verifiers` with Bohrin
  out of the loop. The environment's docstring cites a mean reward of 1.0 as evidence that
  per-rollout isolation works; that evidence does not hold, since 1.0 is reachable without
  touching the server. Against the other five the operators reported nothing: `glossary`
  and `deepwiki` grade by substring containment and `proposer_solver` by the last integer
  in the reply, all plainly weak, but no model-free operator here constructs a payload that
  exercises them. No false accusation was made in any run.

## [1.0.0] — 2026-09-02

The first release of Bohrin as a verifier auditor.

**On the version number.** The 0.x line on PyPI belonged to a different tool — static
analysis for robot demonstration data — which was renamed and is published as
[`adduct`](https://pypi.org/project/adduct/), with its full history in that repository.
Those releases are yanked and point users there. The major bump is deliberate: this is a
different program, not an upgrade.

**What it measures.** Two probes, and the honest limits of each are reported rather than
implied. `weak_oracle` submits provably-wrong candidates and records the ones a verifier
accepts; a candidate is only reported as an exploit when its wrongness was established
independently of the verifier being audited, and where a reference exists it must pass
first. `determinism` submits one identical candidate repeatedly and reports disagreement,
quoting the detection power of the run because a null result bounds the flake rate rather
than proving determinism.

**Known limits, stated deliberately.** A task whose reward function requires a runtime is
refused rather than scored on a partial rubric. `docs/05_ROBUSTNESS.md` records seven known
weaknesses with the evidence behind each — most importantly that harness disruption is not
yet reported as a finding, and that the false-positive rate is unmeasured until a public
sweep measures one. No accuracy claim is made in the meantime.

### Added

- Design documentation for the open core in `docs/`: architecture, the Verification Gap
  specification, the two open probe designs, and the open/proprietary boundary.
- **Isolation is classified, enforced and recorded.** Scoring runs the taskset's own
  reward functions, which is arbitrary third-party code. Bohrin now refuses to execute it
  with no boundary unless `--unsafe-local` is passed, and the level used is written into
  the report — a result produced in-process must never be mistaken for one produced inside
  a container. The level below a container is called `subprocess` and described as
  blast-radius containment, never a sandbox: process limits prevent denial of service, not
  escape.
- **Concurrency adapts to the machine.** Derived from core count and free memory rather
  than fixed, so an audit does not crowd out the laptop running it. macOS is handled
  explicitly because it exposes no `SC_AVPHYS_PAGES`, which would otherwise leave the
  memory guard permanently disabled on exactly the machines it protects.
- **The `verifiers` v1 adapter.** Bohrin can now audit a real taskset. Candidates are
  scored by constructing a trace and invoking the task's reward functions directly — no
  agent, no model inference, no rollout — so a first audit takes seconds.
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
  yanked and point users at `adduct`; the verifier auditor starts at 1.0.0, so that the
  discontinuity reads as a break rather than an upgrade.

[Unreleased]: https://github.com/prabhu-gopal/bohrin/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/prabhu-gopal/bohrin/releases/tag/v1.0.0
