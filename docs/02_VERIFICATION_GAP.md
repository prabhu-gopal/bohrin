# The Verification Gap

## What it measures

> The distance between what the grader reports happened and what actually
> happened.

Reported 0–100. Low means the verifier is trustworthy. High means the reported
pass rate is substantially fiction.

## The problem with a single number

A metric computed from a variable set of probes is not one metric. If the free
tier reports `VG 34` from two probes and a paid tier reports `VG 34` from six,
those are different quantities wearing the same name. That is dishonest, and it
would destroy the thing the metric exists to become — a number people cite.

The fix is borrowed from test coverage, which has the identical problem and
solved it long ago: **a coverage figure is always reported with what it
covered.**

```
VERIFICATION GAP: 34 / 100     coverage: 2 of 6 probes
                               (weak-oracle, determinism)
```

Three properties follow, and all three are wanted:

1. The free number is **real and citable**. It is not a teaser.
2. The paid number is **visibly more complete** without the free one being
   crippled. The upgrade argument is coverage, not unlocking.
3. Two audits are only comparable when their coverage matches, and the report
   makes that checkable rather than assumed.

**A Verification Gap printed without its coverage descriptor is malformed.**
This holds in the terminal, the HTML report, the JSON, and the certificate.

## Computation

Each probe returns a normalised sub-score in `[0, 1]`, where 0 is a clean
verifier and 1 is maximally compromised. The gap is the weighted mean over
probes that **ran and completed**, scaled to 0–100.

```
VG = 100 × Σ(wᵢ · sᵢ) / Σ(wᵢ)     over completed probes i
```

Rules, all of which exist to prevent a number that lies:

- A probe that errors is **excluded from both sums** and reported as errored.
  It is never scored 0, which would read as "clean".
- A probe that ran and found nothing scores 0 and **is** included. Absence of
  evidence is evidence here, but only when the probe actually ran.
- Weights are declared in `scoring/gap.py`, versioned with the schema, and
  published. A metric with undisclosed weights cannot be independently
  reproduced, and reproducibility is what substitutes for accreditation.

### Initial weights

Equal weighting at 1.0.0. This is a deliberate refusal to over-engineer: there is
no evidence yet on which probe best predicts real harm, and inventing weights
would be a claim we cannot support.

Weights change only on measured evidence from the public index, and any change
bumps the schema version — because a score whose meaning silently shifted is
worse than no score.

## Per-probe sub-scores

Each probe defines its own normalisation, documented with it in
[03_PROBES.md](03_PROBES.md).

| Probe | Sub-score |
|---|---|
| `weak_oracle` | fraction of tasks accepting at least one known-wrong candidate |
| `determinism` | fraction of tasks where an identical submission scored differently across repeats |

Both are proportions of tasks, not counts, so a 40-task and a 400-task
environment produce comparable numbers.

The scoring probes deliberately measure different failure modes — `weak_oracle`
measures *correctness* of acceptance, `determinism` measures *reliability* of
scoring. A verifier can fail either independently, so neither subsumes the
other and the pair gives real coverage rather than two views of one defect.

## Reporting uncertainty

A sub-score is a proportion of tasks, and a proportion is only as good as the number of
tasks under it. `2 of 2` and `300 of 300` both read as "every task compromised"; the first
is a lead and the second is a measurement. The coverage descriptor above says which
*probes* contributed, and cannot say how many *tasks* each one managed to measure — which
is where a large number can be built from almost nothing. Measured on a synthetic
environment before this rule existed: `weak_oracle` could measure only 2 of 20 tasks, and
the report printed `VERIFICATION GAP: 50 / 100 coverage: 2 of 2 probes`.

So every rate carries its sample size and a 95% **Wilson score interval** — in the terminal,
directly beneath the gap (`rests on: weak_oracle 2 of 2 tasks (95% CI 34–100%)`), and in
`--json` as `detail.rate`: `affected`, `measured`, `interval_95`.

**Why Wilson.** The textbook `p ± 1.96·√(p(1−p)/n)` fails exactly where an audit's samples
live: at small `n`, and at `p` near 0 or 1 — which is where a clean or a fully compromised
verifier puts it. At `2 of 2` it collapses to `[1, 1]`, claiming certainty from two
observations. Brown, Cai and DasGupta's comparison of nine methods (*Statistical Science*,
2001) recommended Wilson for small samples; recent guidance on evaluating agents over
small task sets makes the same recommendation, with uncertainty reported per task set
rather than only in aggregate.

**An interval needs a sample.** A Wilson interval says how far the measured rate may sit
from the rate of the population the tasks were drawn from — which is the taskset only when
the tasks were drawn at random. `--max-tasks N` takes the *first* N, and a taskset is
routinely ordered by subject, source or difficulty, so a prefix rate describes the prefix
and the interval around it describes the prefix too. `--sample-seed S` draws the N
uniformly at random instead, and the report records the mode and the seed
(`100 random of 3270 tasks (seed 7)`, and `selection` in `--json`) so a reader can tell
which of the two claims a number is making. Any published rate over a bounded audit should
be sampled; the prefix remains the default because it is what an unseeded command has
always meant.

**What it does not describe.** Sampling uncertainty only. Whether the operators could
construct the relevant payload at all is a separate and qualitative limit, stated by the
caveat the report prints under any clean result.

## What the gap is not

- **Not a benchmark score.** There is no leaderboard, and Bohrin will not
  publish one for private environments.
- **Not a safety claim.** It measures verifier integrity. Whether a leaky
  verifier damages a trained model is contested in the literature, and the
  metric deliberately does not depend on the answer.
- **Not comparable across coverage levels.** See above.

## Reproducibility

The specification in this document, the weights, and the reference
implementation are open. Anyone — including a lab receiving a certificate — can
recompute the number from the same inputs.

This is not incidental. Established assurance regimes derive credibility from an
accrediting authority; none exists here and none can be obtained. Public,
reproducible methodology is the only available substitute, which makes the
openness of this layer a requirement of the certification business rather than a
marketing choice.
