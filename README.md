# bohrin

[![PyPI](https://img.shields.io/pypi/v/bohrin.svg)](https://pypi.org/project/bohrin/)
[![CI](https://github.com/prabhu-gopal/bohrin/actions/workflows/ci.yml/badge.svg)](https://github.com/prabhu-gopal/bohrin/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Bohrin finds the defects in your robot demonstration data that will break your policy —
before you spend four hours training.**

```console
$ bohrin scan lerobot/pusht

bohrin  ·  lerobot/pusht
lerobot_v3 · 206 episodes · unknown · 10 Hz · action_dim 2
╭──────────────────╮
│ 3 MEDIUM   4 LOW │
╰──────────────────╯
by family: smoothness 3  dynamics 2  stats 1  temporal 1

MEDIUM ▸ The dataset's distribution shifts partway through collection
         → Check for a recalibration, tool change, or operator change 
midway; consider treating the segments as separate datasets.
           206 eps  [stats.distribution_drift]

LOW    ▸ State evolves inconsistently with the actions in 2.0% of 
transitions (206 episodes)
         → Inspect the flagged segments; drop episodes containing resets or 
frame drops.
           206 eps  [dynamics.forward_residual]

LOW    ▸ Logged actions don't explain 2.0% of transitions, spread over 206 
episode(s)
         → Inspect the flagged episodes for recording misalignment or 
dropped frames; re-sync the action and observation streams.
           206 eps  [dynamics.inverse_residual]

MEDIUM ▸ Same state, different next action in 74 episode(s)
         → Prefer action chunking (ACT) or Diffusion Policy over plain BC.
           74 eps  [temporal.non_markovian_pause]

MEDIUM ▸ Shaky teleoperation in 9 episode(s) (up to 6.3× median jerk)
         → Re-record or smooth the flagged episodes; consider a low-pass 
filter on teleop input.
           9 eps  [smoothness.jerk_outlier]

LOW    ▸ 4 episode(s) wander: up to 18.6× the direct path
         → Review the flagged episodes; re-record the ones where the 
operator was searching.
           4 eps  [smoothness.path_efficiency]

… 1 more finding(s).
Next: bohrin scan lerobot/pusht --html report.html --open
```

That is a real, unedited run against a real public dataset — about two seconds on a laptop
with a warm cache, no GPU, and no video decoded. Findings are ordered by
severity × blast radius, so a dataset-wide LOW can outrank a narrow MEDIUM: the top of the
list is what to look at first, not simply what is loudest.

## Install

```bash
pip install bohrin
bohrin scan lerobot/pusht
```

Python 3.10–3.13. Point it at a local directory or a Hugging Face Hub `owner/name`.

## What it checks

Bohrin ships 48 detectors across 12 families — 46 run by default, 2 are held back
pending recalibration (see below) and reachable with `--all`. What makes a finding useful is not that
something is statistically unusual — it is the **mechanism**: why this specific defect
degrades a trained policy. Every finding carries one, plus the measured value, the
threshold it crossed, the affected episodes, and a concrete fix.

| Check | Why it breaks training |
| --- | --- |
| **A dead action dimension** | The policy learns to predict a constant for that joint. When the joint matters at deployment, there is no signal to learn from — and the loss never told you, because predicting a constant is easy. |
| **Declared stats disagreeing with measured data** | Normalization is computed from `stats.json`. If it disagrees with the data, every input is scaled wrong — train and validation silently normalize differently, and the loss curve looks fine while the policy learns nothing transferable. |
| **Jitter and jerk outliers** | Behavior cloning fits the noise. High-frequency teleop tremor becomes a learned output signature, which is both wrong and physically hard on the robot. |
| **Actions that don't explain state transitions** | The action and observation streams are misaligned. The policy is being asked to learn a mapping that does not exist in the data. |
| **Same state, different next action** | Plain BC averages the modes and produces the mean of two valid behaviors, which is often a third, invalid one. This is a signal to use action chunking or a diffusion policy, not a bug to fix. |
| **Single-strategy coverage** | The policy works from the one starting configuration you demonstrated and fails from anywhere else. This is invisible in training metrics and obvious on the robot. |

Run `bohrin list-detectors` for the full set, or `bohrin explain <id>` for the mechanism
behind any one of them.

## What it does **not** do

Being clear about this matters more than any feature claim:

- **No simulator, no training, no GPU.** It reads your data and does statistics on it.
- **No network**, except the explicit Hugging Face fetch when you pass a `owner/name` repo
  id. Local scans make zero network calls.
- **No telemetry.** Nothing about your data, your findings, or your usage is transmitted
  anywhere. Ever. There is no opt-out because there is nothing to opt out of.
- **It never decodes video by default.** It reads Parquet columns, which is why it is fast.
- **It does not catch everything.** Some failure modes only show up in a rollout — a policy
  that is subtly bad at a contact-rich sub-task will look fine to every static check here.
  Bohrin rules out a class of data problems; it does not certify that a dataset is good.
- **The findings are not calibrated against training outcomes yet.** They are grounded in
  documented failure mechanisms, not in a corpus of runs that measures how much each defect
  actually costs. Treat severity as a triage ordering, not a prediction.
- **Two detectors are excluded from a default scan.** On a 20-dataset sweep of curated
  public LeRobot data, `smoothness.discontinuity_jump` and `integrity.declared_mismatch`
  reported HIGH on 70% and 60% of datasets respectively — common enough that they were
  winning the visible top of the report with an untrustworthy finding, on data that has no
  reason to be that broadly defective. Pass `--all` to run them anyway; nothing is deleted,
  just held back pending recalibration. Please
  [report them as false positives](https://github.com/prabhu-gopal/bohrin/issues/new?template=false_positive.yml)
  if they fire on data you trust. The sweep is reproducible: `python scripts/hub_smoke.py`.

## Measured evidence

The unit suite plants known defects in synthetic fixtures and checks they are found — that
measures recall, and it cannot measure precision on healthy data. [`benchmarks/`](benchmarks/)
holds the runs that measure the other half, on real published datasets.

The latest, [**Bohrin on 20 public LeRobot datasets**](benchmarks/2026-08-26-hub-sweep-v0.1.0/REPORT.md)
(2,631 episodes, 545,964 frames): all 20 parsed without error in 20.8 s total on a laptop
CPU, producing 187 findings. Of the 46 default detectors, 27 fired at least once, 19 never
fired, and only 4 ever reached HIGH. It also flags one of bohrin's own detectors,
`dynamics.inverse_residual`, as reporting HIGH too often to be trusted yet — and is explicit
that a fire rate is a rate of complaint, not a rate of correctness.

## Supported formats

| Format | Status |
| --- | --- |
| LeRobot v2.1 | ✅ Autodetected, local or Hub |
| LeRobot v3.0 | ✅ Autodetected, local or Hub |
| RLDS / Open-X | ✅ Needs `pip install bohrin[rlds]` |
| robomimic HDF5 | ✅ Needs `pip install bohrin[hdf5]` |
| Raw HDF5 | ✅ Needs `pip install bohrin[hdf5]` |
| Zarr replay buffer | ✅ Needs `pip install bohrin[zarr]` |
| NumPy directory | ✅ Built in |

Using something else? [Tell us which format](https://github.com/prabhu-gopal/bohrin/issues/new?labels=format-request&title=%5Bformat%5D+)
— what gets built next is decided by what people actually have.

## Found a false positive?

**Please report it.** This is the most valuable thing you can send us.

Bohrin's only real asset is that its findings are trustworthy, and a detector that cries
wolf is worse than no detector. We cannot find those on synthetic data — we need yours.

👉 **[Report a false positive](https://github.com/prabhu-gopal/bohrin/issues/new?template=false_positive.yml)**

You do not need to share your dataset. The detector id, the numbers bohrin printed, and
why it is wrong is enough to act on.

## Using it in CI

By default `bohrin scan` exits `0` whether or not it finds anything, so it never breaks a
pipeline you did not ask it to gate. Opt in explicitly:

```bash
bohrin scan ./data --ci --fail-on HIGH    # exit 1 only when a HIGH finding is present
```

| Exit code | Meaning |
| --- | --- |
| `0` | The scan completed. Findings alone do not change this. |
| `1` | An internal error, or the `--ci --fail-on` gate tripped. |
| `2` | A usage error: bad path, unknown format, unreadable checkpoint. |

Machine-readable output: `--json` (stable, versioned `schema_version`), `--sarif` (SARIF
2.1.0 for GitHub code scanning), `--html` (a self-contained report). Findings go to
stdout; errors, notices, and progress go to stderr, so `bohrin scan ./data --json - | jq`
works cleanly.

## Python API

```python
import bohrin

report = bohrin.scan("./my_lerobot_dataset")
for cluster in report.clusters:
    print(cluster.severity, cluster.title)

report.to_json("report.json")
```

## Extending it

Adapters and detectors are plugins discovered through entry points — the same mechanism
the built-ins use, with no privileged path for first-party code:

```toml
[project.entry-points."bohrin.detectors"]
"myteam.my_check" = "my_pkg.checks:MyCheck"
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Commits need a DCO sign-off (`git commit -s`);
there is no CLA, and you keep the copyright to what you write.

Security issues: please report privately per [SECURITY.md](SECURITY.md), never as a public
issue.

## License

[Apache-2.0](LICENSE). Copyright 2026 Bohrin.
