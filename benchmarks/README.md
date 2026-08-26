# Benchmarks

Measured evidence about how bohrin behaves on real, public robot demonstration data.

The unit suite in [`tests/`](../tests) plants a known defect in a synthetic fixture and
checks the matching detector finds it. That measures **recall**. It cannot measure
**precision on healthy data**, because there is no healthy real data in the fixtures — a
detector that returned HIGH unconditionally would pass every test in the suite.

This directory holds the runs that measure the other half.

## Runs

| Run | Corpus | Bohrin | Headline |
| --- | --- | --- | --- |
| [`2026-08-26-hub-sweep-v0.1.0`](2026-08-26-hub-sweep-v0.1.0/REPORT.md) | 20 public LeRobot datasets · 2,631 episodes · 545,964 frames | 0.1.0 | 20/20 parsed in 20.8 s; 187 findings; one detector's HIGH rate flagged as untrustworthy |

## How a run directory is organized

```
<YYYY-MM-DD>-<corpus>-v<bohrin-version>/
├── REPORT.md              the report — findings, method, and limitations
├── results/sweep.json     raw machine-readable output, committed
├── figures/               charts (PNG for Markdown, PDF for LaTeX)
├── paper/                 LaTeX source + compiled PDF
└── scripts/               regenerates every figure from results/
```

## Rules for this directory

These follow the same reasoning as `CHANGELOG.md`'s released sections and ACM's artifact
documentation norms.

1. **A run directory is an immutable record.** Once committed, its numbers describe what
   that version of bohrin did on that date. Fix a mistake with a correction note inside the
   report or a new run — never by silently rewriting a published number.
2. **Raw results are committed alongside the prose.** `results/sweep.json` is the
   authority. If a figure or a sentence disagrees with it, the JSON is right.
3. **Every figure regenerates from the committed results.** No number is transcribed by
   hand into a chart. `scripts/make_figures.py` reads `results/` and nothing else.
4. **Every run states its provenance**: commit SHA, bohrin version, dependency versions,
   platform, and the exact command that produced it.
5. **Every run has a limitations section, and it is not decorative.** Say plainly what the
   numbers do *not* establish. A fire rate is not a precision measurement, and a report
   that lets a reader confuse the two is worse than no report.
6. **Reporting tools stay out of `pyproject.toml`.** `matplotlib` and LaTeX are used here
   and are not bohrin dependencies — the dependency policy is that a declared dependency
   must be imported by shipped code.

## Adding a run

```bash
git checkout -b benchmark-<something>
mkdir -p benchmarks/$(date +%F)-<corpus>-v<version>/{results,figures,paper,scripts}
python scripts/hub_smoke.py --json benchmarks/<run>/results/sweep.json
```

Then write `REPORT.md`, generate figures from the JSON, and add a row to the table above.
Like every other change in this repo, it goes through a branch and a pull request.
