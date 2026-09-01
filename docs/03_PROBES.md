# The open probes

Two probes ship in the open core. This document is their design, including the
parts that are hard and the parts we deliberately refuse to do.

---

## Probe 1 — Weak Oracle

> Will this verifier accept work that is provably incorrect?

### Formal foundation

This is **mutation testing**, with the roles relabelled.

In mutation testing you seed small faults into code and run the test suite. A
mutant the suite fails to catch is a *surviving mutant*, and it identifies a
weakness in the tests. The mutation score is the proportion killed.

Map it onto this domain:

| Mutation testing | Bohrin |
|---|---|
| Code under test | The candidate solution |
| Test suite | **The verifier** |
| Surviving mutant | A wrong solution the verifier **accepted** |
| Mutation score | Inverse of the weak-oracle sub-score |

The relabelling is the whole idea: mutation testing normally judges tests by
whether they catch bad code; here the verifier *is* the test suite, and every
survivor is a false positive in a live reward function. Decades of literature
and tooling (`mutmut`, `cosmic-ray`, MutPy, `mutatest`) apply directly, which is
also why we make no novelty claim.

### Algorithm

```
for task in tasks:
    base ← reference solution, if the taskset provides one
    for op in enabled_operators:
        mutant ← op.apply(base)
        if not established_wrong(mutant, task):   # see below
            continue                              # never guess
        verdict ← score(task, mutant)
        if verdict.passed:
            record Exploit(task, mutant, op, verdict)
```

Sub-score = (tasks with ≥1 recorded exploit) / (tasks probed).

### Establishing wrongness

**This is the crux of the entire probe, and where a naive implementation
becomes a liability.**

Mutation testing has a well-known defect: the *equivalent mutant* problem. A
mutation can alter the source without altering behaviour. Such a mutant
"survives", but the test suite was right to accept it — there is no fault to
find. In ordinary mutation testing this inflates a score. Here it would cause
Bohrin to tell a customer their verifier is broken when it is correct.

Recall the governing rule: **Bohrin must never falsely accuse a verifier.** So a
mutant is only admissible as an exploit when its incorrectness is established
**independently of the verifier under audit**. Three admissible grounds:

1. **Differential.** The mutant and the reference produce different observable
   results on at least one concrete input. Strongest ground; requires a
   reference solution and an executable comparison.
2. **Structural.** The mutation provably removes required behaviour — the
   deliverable is deleted, the function body is emptied, a required side effect
   is dropped. Wrongness is established by construction.
3. **Declared invariant.** The mutant violates an invariant the taskset itself
   asserts, independently of the reward function being probed.

If none applies, the candidate is **not** submitted, and if submitted-and-passed
it is recorded as `unverified` and **excluded from the score**, surfaced only in
a separate advisory section of the report.

> A verifier is reported as broken only when Bohrin can show the accepted
> submission is wrong. Everything else is a lead, not a finding — and the report
> must never blur the two.

### Mutation operators — the free baseline

Deterministic, no model inference, therefore fast and reproducible. Each is
tagged with the wrongness ground it can establish.

| Operator | Mutation | Ground |
|---|---|---|
| `constant_return` | Replace body with `return <literal>` | Structural |
| `empty_body` | Replace body with `pass` / no-op | Structural |
| `drop_side_effect` | Remove the persistence/write, keep the return | Structural |
| `negate_condition` | Invert a branch predicate | Differential |
| `off_by_one` | Perturb a boundary by ±1 | Differential |
| `swap_operator` | `<`↔`<=`, `+`↔`-`, `and`↔`or` | Differential |
| `identity_return` | Echo the input unchanged | Structural |

`drop_side_effect` is the highest-yield operator in this domain and deserves
comment: a reward function that checks a return value but never inspects the
database or filesystem accepts a solution that reports success without doing the
work. That is the single most common shape of the 28.5% finding.

**What is withheld:** this baseline is bounded to published, mechanical
mutations. The proprietary attack engine adds model-generated, verifier-aware
exploit synthesis and the accumulated corpus. The open harness with the baseline
operators finds real defects; it does not find what a frontier attacker finds.
That gap is honest, durable, and requires no crippling of the open code.

### Performance

Scoring calls the reward function directly on a constructed `Trace` — no agent,
no rollout. Cost is one reward invocation per admissible mutant. With ~7
operators over 40 tasks that is a few hundred cheap async calls, run concurrently
with a bounded semaphore. A first audit completes in seconds.

---

## Probe 2 — Determinism

> Does the verifier return the same reward for the same submission?

### Why not composition

The original plan named **composition** as the second open probe: satisfy each
rubric criterion in isolation, then check whether they hold jointly. It was
dropped on measurement, not on taste.

Sampling real tasksets from the public `research-environments` catalogue:

| Environment | Reward functions |
|---|---|
| `code/humaneval` | 1 |
| `math/aime25` | 1 |
| `swe/multiswe` | 1 |
| `tool_use/bfcl_v3` | 1 |
| `code/forth_lang` | 1 |
| `tool_use/enterprise_ops_gym` | 1 |
| `terminal/terminal_bench_2` | 0 at the sampled path |

Composition requires **≥2** reward functions. Six of seven real environments
have exactly one, so the probe would report `not_applicable` across essentially
the entire public ecosystem — contributing nothing to the gap, and leaving the
free tier as a single-probe tool.

A probe that cannot run on the corpus it was built for is not a probe. Composed
held-out test synthesis remains the right technique, but it needs real semantic
understanding of the task, which places it in the proprietary engine.

### The replacement

Determinism is chosen because it is **universal** — it needs no rubric
structure, no reference solution, and works identically on a single-reward-
function task, which is what the ecosystem actually contains.

A verifier that returns different rewards for an identical submission is
unreliable by definition. In an RL context this is not cosmetic: it injects
noise directly into the reward signal, and it is a common real defect —
timeouts, network access, unseeded randomness, filesystem or ordering
dependence, and clock sensitivity all produce it.

### Algorithm

```
for task in tasks:
    cand ← reference solution if available, else a fixed synthetic submission
    rewards ← [ await score(task, cand) for _ in range(N) ]   # N = 5 default
    if len(set(rewards)) > 1:
        record Flake(task, rewards, spread=max-min)
```

Runs are serialised by default; a `--concurrent-determinism` flag additionally
probes for order- and parallelism-dependence, reported as a distinct finding
class because the cause differs.

Sub-score = (tasks exhibiting variance) / (tasks probed).

### Why it cannot false-accuse

This is the probe's strongest property and the reason it suits the open tier.

Every other probe *infers* that a verifier is wrong. Determinism **observes** it
directly: the same bytes were submitted N times and the grader disagreed with
itself. There is no equivalent-mutant problem, no correctness judgement, and no
reference oracle required.

The evidence is also instantly checkable by the customer —

```
Task 7: reward 1.0, 0.0, 1.0, 1.0, 0.0 for an identical submission
```

— which makes it credible on sight and an unusually good first finding for a
tool nobody has heard of.

### Honest scope limit

A verifier may be perfectly deterministic and still be badly wrong. This probe
measures reliability, not correctness, and the report must not imply otherwise.
It is reported as its own family (`reliability`) rather than folded into
acceptance findings.

---

## Common contract

```python
class Probe(ABC):
    id: str                 # "weak_oracle"
    family: str             # "acceptance" | "reliability"
    weight: float

    def explain(self) -> str: ...
    async def run(self, source: TaskSource, cfg: ScanConfig) -> ProbeResult: ...

@dataclass(frozen=True, slots=True)
class ProbeResult:
    probe_id: str
    status: Literal["ok", "not_applicable", "error"]
    sub_score: float | None       # None unless status == "ok"
    exploits: tuple[Exploit, ...]
    unverified: tuple[Candidate, ...]   # leads, never scored
    tasks_probed: int
    detail: Mapping[str, Any]
```

`status` is not cosmetic. `not_applicable` and `error` are excluded from the gap
computation; only `ok` contributes. This is what stops a probe that could not run
from being read as a clean bill of health.

## Testing these probes

Mirroring the previous codebase's discipline, and enforced in CI:

1. **Fault injection.** A fixture taskset with a deliberately weak verifier,
   where the exact set of exploits is known. A probe that misses a planted
   exploit fails the build.
2. **A clean fixture.** A taskset with a genuinely strong verifier, where the
   correct answer is *zero* exploits. **A probe that reports a finding here
   fails the build.** This is the false-accusation guard and it is the more
   important of the two.
3. **Equivalent-mutant fixture.** Mutants that are behaviourally identical to
   the reference. These must be filtered before submission, never reported.
4. **A registry test** that fails the build if any registered probe lacks a
   fixture in (1) and (2).
