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
| [`2026-08-26-lerobot-20-v0.1.0`](2026-08-26-lerobot-20-v0.1.0/REPORT.md) | 20 public LeRobot datasets · 4,342 episodes · 545,964 frames | 0.1.0 | 20/20 parsed in 22.3 s; 189 findings; one detector fails its own audit |

## How a run directory is organized

```
<YYYY-MM-DD>-<corpus>-v<bohrin-version>/
├── REPORT.md                   the report: findings, method, and limitations
├── results/sweep_full.json     raw output, every episode read
├── results/sweep_default.json  raw output under the default triage cap
├── figures/                    charts (PNG for Markdown, PDF for LaTeX)
├── paper/                      LaTeX source + compiled PDF
└── scripts/                    re-runs the sweep and regenerates every figure
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
6. **Distinguish episodes scanned from episodes present.** A default scan is triage and
   caps at `DEFAULT_TRIAGE_EPISODES`. Reporting the scanned count as the corpus size, or
   pairing it with a frame count read from `meta/info.json`, mixes two populations. An
   earlier draft of the first run did exactly this; `DatasetInfo` exposes both
   (`n_episodes`, `total_episodes`), so record both.
7. **Claim only what a primary source supports.** Robot platforms, provenance, and
   sim-versus-real were verified against published sources where possible and left
   unclaimed where not. A benchmark's credibility does not survive one wrong robot name.
8. **Reporting tools stay out of `pyproject.toml`.** `matplotlib` and LaTeX are used here
   and are not bohrin dependencies: the policy is that a declared dependency must be
   imported by shipped code.

## Adding a run

```bash
git checkout -b benchmark-<something>
mkdir -p benchmarks/$(date +%F)-<corpus>-v<version>/{results,figures,paper,scripts}
# copy scripts/ from the previous run, then:
python scripts/run_sweep.py --out results/
```

Then write `REPORT.md`, generate figures from the JSON, and add a row to the table above.
Like every other change in this repo, it goes through a branch and a pull request.
