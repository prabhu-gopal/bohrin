# The Verification Gap

## What it measures

> The distance between what the grader reports happened and what actually
> happened.

Reported 0–100. Low means the verifier is trustworthy. High means the reported
pass rate is substantially fiction.

## The problem with a single number

A metric computed from a variable set of checks is not one metric. `VG 34` from two
checks and `VG 34` from six are different quantities wearing the same name. That is
dishonest, and it would destroy the thing the metric exists to become — a number people
cite.

The fix is borrowed from test coverage, which has the identical problem and solved it
long ago: **a coverage figure is always reported with what it covered.**

```
VERIFICATION GAP: 34 / 100     coverage: 2 of 6 probes
                               (weak_oracle, determinism)
```

Two properties follow, and both are wanted:

1. Every number is **real and citable**, whatever coverage produced it.
2. Two results are only comparable when their coverage matches, and the coverage
   descriptor makes that checkable rather than assumed.

**A Verification Gap shown without its coverage descriptor is malformed**, wherever it is
shown. `GapScore.__str__` renders the two together so the easy path is also the correct one.

## Computation

Each check returns a normalised sub-score in `[0, 1]`, where 0 is a clean verifier and 1 is
maximally compromised. The gap is the weighted mean over checks that **ran and completed**,
scaled to 0–100.

```
VG = 100 × Σ(wᵢ · sᵢ) / Σ(wᵢ)     over completed checks i
```

Rules, all of which exist to prevent a number that lies:

- A check that errors is **excluded from both sums** and recorded as errored. It is never
  scored 0, which would read as "clean".
- A check that ran and found nothing scores 0 and **is** included. Absence of evidence is
  evidence here, but only when the check actually ran.
- Weights are published in `scoring/gap.py` as `WEIGHTS`. A metric with undisclosed weights
  cannot be independently reproduced, and reproducibility is what substitutes for
  accreditation.

### Weights

| Check | Weight | Family |
|---|---|---|
| `weak_oracle` | 1.0 | acceptance |
| `determinism` | 1.0 | reliability |
| `ground_truth_rejected` | 0.0 — reported, never counted | rejection |
| `answer_leakage` | 0.0 — reported, never counted | task validity |

Equal weighting for the checks that can be scored soundly. This is a deliberate refusal to
over-engineer: there is no evidence yet on which check best predicts real harm, and inventing
weights would be a claim that cannot be supported. The two checks at zero are kept out of the
headline for soundness reasons given in [03_PROBES.md](03_PROBES.md). A check not named in
the table takes a weight of 1.0.

Weights change only on measured evidence, and a change is recorded in the changelog —
because a score whose meaning silently shifted is worse than no score.

## Per-check sub-scores

| Check | Sub-score |
|---|---|
| `weak_oracle` | fraction of tasks accepting at least one known-wrong candidate |
| `determinism` | fraction of tasks where an identical submission scored differently across repeats |
| `ground_truth_rejected` | fraction of tasks refusing every rendering of their own declared answer |
| `answer_leakage` | fraction of checked tasks whose declared answer is in their own prompt |

All are proportions of tasks, not counts, so a 40-task and a 400-task environment produce
comparable numbers.

The scored checks deliberately measure different failure modes — `weak_oracle` measures
*correctness* of acceptance, `determinism` measures *reliability* of scoring. A verifier can
fail either independently, so neither subsumes the other.

## Two sides

A reward signal can be wrong in two directions: paying for wrong work, and refusing right
work. They are different defects with different fixes, so both are reported beside the
headline:

```
VERIFICATION GAP: 50 / 100   coverage: 4 of 4 probes
sides: acceptance 50 / 100 · rejection 12 / 100 (the rejection side is reported, not counted in the gap)
```

Each side is the **unweighted** mean of the sub-scores of its completed checks — `acceptance`
and `rejection` families respectively — and a side none of whose checks completed is `None`,
never 0. Unweighted because a check's gap weight decides whether it may move the headline,
which is a soundness question, not a statement about how it compares with checks on its own
side. The sides never change the headline.

## Reporting uncertainty

A sub-score is a proportion of tasks, and a proportion is only as good as the number of tasks
under it. `2 of 2` and `300 of 300` both read as "every task compromised"; the first is a lead
and the second is a measurement. The coverage descriptor says which *checks* contributed, and
cannot say how many *tasks* each one managed to measure — which is where a large number can
be built from almost nothing. Measured on a synthetic environment: `weak_oracle` could measure
only 2 of 20 tasks, and the gap read `50 / 100` at full coverage.

So every rate carries its sample size and a 95% **Wilson score interval**
(`scoring.interval.rate`: `affected`, `measured`, `interval_95`).

**Why Wilson.** The textbook `p ± 1.96·√(p(1−p)/n)` fails exactly where these samples live: at
small `n`, and at `p` near 0 or 1 — which is where a clean or a fully compromised verifier puts
it. At `2 of 2` it collapses to `[1, 1]`, claiming certainty from two observations. Brown, Cai
and DasGupta's comparison of nine methods (*Statistical Science*, 2001) recommended Wilson for
small samples; recent guidance on evaluating agents over small task sets makes the same
recommendation, with uncertainty reported per task set rather than only in aggregate.

**An interval needs a sample.** A Wilson interval says how far the measured rate may sit from
the rate of the population the tasks were drawn from — which is the taskset only when the
tasks were drawn at random. The first N tasks are not a sample: a taskset is routinely
ordered by subject, source or difficulty, so a rate over a prefix describes the prefix, and
the interval around it describes the prefix too. Measured on a published environment: a
10-task prefix scored 0 and a 20-task prefix scored 50 on the same verifier, because the
tasks carrying the defect sat at positions 11 and 12. Any published rate over part of a
taskset should rest on a seeded uniform sample, with the seed recorded.

**What it does not describe.** Sampling uncertainty only. Whether the battery could construct
the relevant payload at all is a separate and qualitative limit: a clean result bounds what
the battery could construct, and is not a proof that the verifier is sound.

## The Coverage Score

The Gap asks how often the reported pass rate is fiction. The Coverage Score asks the question
a grader's author reads as a grade: **of the known ways this task can be passed without doing
it, what fraction does this grader catch?** Reported 0–100, higher is better, from
`scoring.coverage.coverage_score`.

The unit is a **task and a category**. Each operator declares the category its candidates
count towards, and the categories are published with a version, `BATTERY_VERSION`:

| Category | The way of passing without doing the work |
|---|---|
| `empty_and_echo` | no answer at all: an empty reply, the question repeated back, or a refusal |
| `denial` | an explicit denial of the declared answer |
| `multiple_answers` | several different answers stated at once, the declared one among them |
| `malformed_output` | a reply a policy produces when generation goes wrong, holding no answer |
| `wrong_answer` | a definite answer, or a program, provably different from the declared one |

Rules, each of which exists to stop the number overstating what was checked:

- A category is **measured** on a task when at least one grounded candidate of it was tried,
  and **caught** only when the grader accepted none of them. One accepted candidate is enough
  for the category to get through on that task.
- **Leads never count**, in either direction. A candidate whose wrongness could not be
  established says nothing about the grader.
- **Nothing measured is not 100.** A result with no grounded attempts is `not measured`.
- The score always carries its sample (`caught` of `measured`), a 95% Wilson interval, the
  categories it covered, and the battery version. Two scores are comparable only over the same
  categories and version.
- A candidate from an operator that declares no category counts as `other`, and is never
  claimed as coverage of a published category.

## What the gap is not

- **Not a benchmark score.** There is no leaderboard.
- **Not a safety claim.** It measures verifier integrity. Whether a leaky verifier damages a
  trained model is contested in the literature, and the metric deliberately does not depend
  on the answer.
- **Not comparable across coverage levels.** See above.

## Reproducibility

The specification in this document, the weights, and the reference implementation are open.
Anyone can recompute the number from the same inputs.

This is not incidental. Established assurance regimes derive credibility from an accrediting
authority; none exists here. Public, reproducible methodology is the only available
substitute, which makes the openness of this layer a requirement rather than a marketing
choice.
