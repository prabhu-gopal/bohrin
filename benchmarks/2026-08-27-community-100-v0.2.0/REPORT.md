# Native community LeRobot datasets — corpus selected, sweep pending

**Status: incomplete.** The corpus is selected and pinned; the sweep has not been run.
This file exists so the next session starts from a stated position rather than from memory.

| | |
| --- | --- |
| Corpus | 100 community LeRobot datasets, pinned by commit SHA |
| Manifest | [`results/manifest.json`](results/manifest.json) |
| Sweep | **not run** — no `results/sweep.json` yet |
| Bohrin version | 0.2.0 (plus unmerged `owner/name@revision` support) |

## Why this corpus exists

The first corpus (`benchmarks/2026-08-26-lerobot-20-v0.1.0/`) has a defect it documents in
its own limitations. Fourteen of its twenty datasets are Open X-Embodiment conversions
recorded at 5 Hz, and every native dataset in it runs faster. Control rate and conversion
provenance are therefore perfectly confounded, so that corpus cannot separate a threshold
bug from an artifact of format conversion. It also says little about the user bohrin is
built for: someone teleoperating a low-cost arm and recording at 20–50 Hz natively.

This corpus breaks the confound.

## What was selected

Probed 122 candidates, selected 100. Selection is mechanical and the rules are recorded in
the manifest: native only (the curated `lerobot/` org is excluded), `fps >= 20`,
`episodes >= 10`, `frames <= 300,000`, must declare an action and a proprioceptive state,
ranked by Hub download count.

| | First corpus (OXE) | This corpus (community) |
| --- | --- | --- |
| Datasets | 20 | 100 |
| Frames | 545,964 | 3,111,325 |
| Episodes | 4,342 | 5,092 |
| Control rate | 14 of 20 at 5 Hz | 92 of 100 at 30 Hz |
| Robots | PR2, Franka, UR5, Stretch, ALOHA | 80 SO-101, 8 SO-100, 3 Koch, 3 LeKiwi |
| Distinct uploaders | a handful of labs | 55 |

Fifty-five distinct uploaders matters: this is community data, not one group's output.

## The finding that does not need the sweep

**Every one of the 100 datasets declares a real `robot_type`. None says `"unknown"`.**

The first corpus reported the opposite: 18 of 20 declared `robot_type: "unknown"`, and that
report concluded an embodiment-keyed calibration scheme built on Hub metadata was unworkable.
That conclusion is wrong as stated, and this corpus corrects it:

| Corpus | `robot_type: "unknown"` |
| --- | --- |
| OXE conversions (first corpus) | 18 / 20 (90%) |
| Native community (this corpus) | **0 / 100 (0%)** |

Native LeRobot recordings declare their embodiment reliably. The Open X-Embodiment
conversion pipeline is what drops the field. So bohrin's Mondrian conformal design, which
keys reference distributions on embodiment, is sound for the population bohrin is aimed at
and fails only on converted lab data.

This changes a conclusion in the first report and needs to be reflected there, not only
here. It also removes a blocker previously recorded against shipping a default calibration
corpus.

## What the sweep is for

Six detectors fire on 70–100% of the first corpus. Whether that is a threshold defect or a
property of twice-converted 5 Hz data is undecidable there. Running this corpus decides it:

- **Similar fire rates on native 30 Hz data** → the thresholds are wrong, and the six need
  the `DEFAULT_EXCLUDED` treatment or recalibration.
- **Sharply lower** → a large share of the first corpus's findings were measuring format
  conversion rather than data quality, which is a result about the ecosystem.

## Next session

```bash
cd benchmarks/2026-08-27-community-100-v0.2.0
python scripts/run_sweep.py --out results/sweep.json    # ~1 hour unauthenticated
```

The sweep checkpoints after every dataset, so it can be stopped and resumed without loss.
`huggingface-cli login` makes it substantially faster: the bottleneck is anonymous Hub rate
limits on many small files, not bandwidth or disk.

An earlier attempt was stopped after 4 datasets and its partial output deliberately not
kept. Four datasets is not a result, and a stub file in `results/` would invite someone to
read it as one.
