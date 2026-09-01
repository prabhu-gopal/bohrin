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

Equal weighting at v0.1. This is a deliberate refusal to over-engineer: there is
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

The two probes deliberately measure different failure modes — `weak_oracle`
measures *correctness* of acceptance, `determinism` measures *reliability* of
scoring. A verifier can fail either independently, so neither subsumes the
other and the pair gives real coverage rather than two views of one defect.

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
