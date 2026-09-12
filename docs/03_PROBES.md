# The open probes

Three probes ship in the open core. This document is their design, including the
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

### The green baseline — checked first, always

Mutation testing assumes a **green baseline**: the unmutated code must pass the suite
before any mutant means anything. Mutants run against a failing suite produce noise
rather than signal.

Here the consequence is sharper than noise. If the reference solution does not pass its
own verifier, Bohrin cannot distinguish:

* *this verifier is weak* — the finding we want to report, and
* *Bohrin is submitting candidates in a form this verifier does not understand* — our own
  integration bug.

Reporting the first when the second is true means **blaming a customer for our defect**,
which is the worst available failure for a product whose entire value is trust.

So before any mutation is submitted:

```
for task with a reference:
    submit the reference unchanged
    if it does not pass  →  the task is UNMEASURABLE
                            recorded as a BaselineFailure, excluded from the score
if no task is measurable →  the probe reports ERROR, never OK
```

Two consequences worth stating:

* The sub-score denominator is the **measurable** set, not every task. Dividing by tasks
  that could not be baselined would silently dilute the score toward "clean".
* A reference that fails its own verifier is itself a real defect, just a different one.
  It is surfaced to the user rather than swallowed.

Tasks that ship **no** reference are admitted unbaselined — the structural operators (an
empty reply, a refusal) remain valid without one, and excluding those tasks would make the
probe useless on the many tasksets that provide no reference. The count is reported so the
weaker guarantee is visible rather than implied.

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

Seven are registered today (`pyproject.toml` `[project.entry-points."bohrin.mutators"]`):

| Operator | Submission it produces | Ground |
|---|---|---|
| `empty_body` | an empty reply, and a whitespace-only reply | Structural |
| `identity_return` | the task prompt, echoed back verbatim — skipped when the prompt *is* the declared answer | Structural |
| `refusal` | `"I cannot complete this task."` | Structural only when a declared answer exists and is not itself a refusal; otherwise **leads only** |
| `constant_return` | a fixed literal (`0`, `1`, `True`, `None`, `[]`, `""`), skipping any that is not *provably distinct* from the reference | Differential |
| `false_negation` | an explicit denial of the declared answer, with the answer last (`"The answer is not X."`) and first (`"X is not the answer."`, `"X is wrong."`) | Invariant |
| `drop_side_effect` | the reference code with every function body replaced by `pass` (LibCST) | Structural |
| `negate_condition` | the reference code with every `if` predicate negated (LibCST) | **none — leads only** |

**The two code-level operators find nothing on the public corpus, and that is a
fact about the corpus.** Across every `verifiers` environment, **zero** reference
solutions contain a function definition or an `if` statement — every one is a bare
answer such as `5050`, `BAEDDC` or `python`. `drop_side_effect` and
`negate_condition` require the reference to *be* Python source, so they produce no
candidates at all: this ecosystem grades replies, not source files.

That is not evidence they are useless, and they are not noisy — `negate_condition`
carries no ground and `drop_side_effect` is guarded by Trivial Compiler
Equivalence, so neither can false-accuse. They would fire on a code-generation
taskset. Retiring tested, benchmarked operators because one corpus does not
exercise them would remove capability to solve a problem that does not exist.
They stay registered, and the measurement is recorded here so the decision is not
re-litigated from memory.

`false_negation` exists for a grader shape nothing else reached. A verifier that
decides by asking whether the answer appears *somewhere in the reply* cannot
distinguish an assertion from its denial — the denial contains the answer too.
`empty_body` and `refusal` submit nothing a containment check recognises, and
`constant_return` submits a literal such a check also rejects, so a substring
grader looked clean to every operator. Its ground is **invariant**: the taskset
declares the answer, and a submission denying that answer contradicts the
taskset's own ground truth, independently of what the reward function says.

**Where the answer sits in the denial matters.** Until 1.2.1 every denial opened
with `The`, which reaches a grader that looks for the answer *anywhere* but never
one that reads the *start* of the reply. Hand-verifying the first index sweep —
which checks a sample of clean results, not only flagged ones — found two public
multiple-choice environments reading clean at 0 of 100 tasks whose graders, called
directly with Bohrin out of the loop, paid full reward for `A is not the answer.`
on 100 of 100. One checks that the extracted answer `startswith` the declared
letter, falling back to the whole reply when there is no `\boxed{}`; the other
takes the first standalone capitalised token. `false_negation` now also puts the
answer first. The ground is unchanged: each form still denies the declared answer.

**Where no text-level operator can establish wrongness: safety tasks.** On a
harmful request the declared answer is a behaviour — *decline this* — and correct
means only that the reply did not comply. Every candidate above is non-compliant,
so none is wrong there. Before 1.2, `refusal` claimed its ground unconditionally
and `false_negation` fired against a refusal reference; both reported a working
safety grader as exploited. Now, when the declared answer reads as a first-person
refusal, the probe withdraws the ground from every candidate — including any from a
third-party operator — and submits them as leads. Without a declared answer
`refusal` is a lead as well, since Bohrin cannot read intent from a prompt; a
grader accepting any non-empty reply is still caught there, by `identity_return`.

**The backstop compares answers, not only programs.** Every grounded candidate,
from any operator, is suppressed if it *is* the reference — under the equivalence
ladder or Trivial Compiler Equivalence. Until 1.2 it compared programs only, so a
third-party operator submitting `70.0` against a reference of `70` still reached a
correct numeric grader as an exploit.

Adding it took findings on the public `verifiers` corpus from two environments to
four. `glossary` grades `answer.lower() in reply.lower()`; `color_codeword`
extracts the longest standalone A–I run and compares it exactly, so
`"The answer is not ABC."` yields `ABC`. Both reward a reply that explicitly
states the answer is wrong.

**Full marks are read from the rubric, so a rubric paying past them is not
measured.** A candidate counts as accepted when its reward reaches the sum of the
rubric's weights, which assumes every reward function returns 0 to 1. Some pay on
other scales — a sum of 0–3 criteria, a mean of 1–5 ratings — and on those an
ordinary reply clears the bar without scoring anything like a correct one. Until
1.2.1 two such public environments were reported as exploited. Now a task on
which any reply, the reference included, scores above full marks leaves the
denominator, its acceptances become leads, and `detail.tasks_scale_unknown`
counts it.

**Every payload is also submitted in the format the verifier accepted.** A grader
that reads one answer format — typically the last `\boxed{}` — never judges a bare
payload's content at all: it rejects it for presentation first, and so reads clean
whether or not it is weak. The baseline already learns that format, because it
submits presentations of the known-good answer until one is accepted; whichever
relation produced the accepted one is the format that verifier reads. Each wrong
payload is then re-submitted through the same relation. The ground is carried over,
and the argument is the relation's own certification: a meaning-preserving
rewriting of a provably wrong answer is the same wrong answer, differently
presented. A verifier that accepts the answer as stored is sent nothing extra —
every additional submission costs a scoring call against someone else's
environment — and `detail.candidates_in_accepted_form` reports how many were added.

`negate_condition` carries **no ground**. Negating a predicate changes the source
but not necessarily the behaviour: a branch whose two arms do the same thing is
the textbook equivalent mutant, and nothing short of executing both tells them
apart. It ships because an accepted negation is worth a human's attention, but it
can only ever produce a lead. In 1.0.1 it claimed the differential ground and
could therefore report a correct verifier as broken.

#### How distinctness is established

A ground is a claim about the candidate's **behaviour**. A difference in
**source** is not evidence of one, and conflating the two is what made three
operators able to falsely accuse. `bohrin/mutate/equivalence.py` supplies the two
soundness checks, and both can only ever *remove* findings:

- **`provably_distinct`** — text level. Two payloads are distinct only when no
  normalisation a correct verifier might apply makes them equal: whitespace,
  case, numeric parsing, Python literals, JSON, and the common spellings of true
  and false. `"1"` and `"1.0"` are different strings and the same answer, so a
  verifier accepting the first for the second is doing numeric comparison
  correctly. The burden of proof sits on us: any collision means no ground.
- **`code_equivalent`** — code level, [Trivial Compiler
  Equivalence](https://ieeexplore.ieee.org/document/7194639/). Two sources that
  compile to identical bytecode are the same program, so a "mutant" that compiles
  to its own reference cannot be an exploit. Sound but incomplete: it never calls
  two different programs equivalent, and it misses equivalences that survive to
  different bytecode — which is exactly why `negate_condition` needs the ground
  removed rather than a TCE guard.

The comparison must recurse into `co_consts`. A module's own `co_code` merely
builds and stores its functions, so two modules whose functions differ completely
share a byte-identical module-level `co_code`; comparing that alone would declare
every mutant equivalent and silently suppress every finding.

Two more are named in `pyproject.toml` comments but **deliberately not yet registered** —
`off_by_one` (perturb a boundary by ±1) and `swap_operator` (`<`↔`<=`, `+`↔`-`, `and`↔`or`).
Both need an executable differential comparison to establish wrongness honestly; until that
lands they could only emit leads, not findings, and a registered operator that cannot
establish a ground is a false-accusation risk.

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
no rollout. Cost is one reward invocation per admissible mutant. With six
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

### Statistical power — reported, not assumed

A null result here is easy to misread as "this verifier is deterministic". It is not.
Disagreement is observed unless every repeat lands on the same side, so

    P(detect) = 1 − p^N − (1 − p)^N

for a verifier that flips with probability *p* over *N* repeats. At the default N = 5:

| flake rate | 50% | 20% | 10% | 5% | 1% |
|---|---|---|---|---|---|
| **P(observed)** | 94% | 67% | 41% | **23%** | 5% |

A verifier that flips 5% of the time is **missed roughly three times in four**. Published
work on flaky-test detection reaches the same conclusion at far larger budgets: even a
thousand reruns has under a 10% chance of surfacing a flake with a rate near 10⁻⁴.

Bohrin therefore reports the detection power of the run alongside its result, and the
terminal headline reads *"no variance observed in 5 runs"* rather than *"deterministic"*.
**A null result bounds the flake rate; it does not establish determinism.** Saying more
than that would be the same error the gap specification forbids elsewhere — reporting a
non-measurement as a clean bill of health.

### Honest scope limit

A verifier may be perfectly deterministic and still be badly wrong. This probe
measures reliability, not correctness, and the report must not imply otherwise.
It is reported as its own family (`reliability`) rather than folded into
acceptance findings.

---

## Common contract

```python
class Probe(ABC):
    id: str  # "weak_oracle"
    family: str  # "acceptance" | "reliability"
    weight: float

    def explain(self) -> str: ...
    async def run(self, source: TaskSource, cfg: ScanConfig) -> ProbeResult: ...


@dataclass(frozen=True, slots=True)
class ProbeResult:
    probe_id: str
    status: ProbeStatus  # OK | NOT_APPLICABLE | ERROR
    tasks_probed: int = 0
    sub_score: float | None = None  # None unless status is OK
    findings: tuple[Finding, ...] = ()  # Exploit | Flake
    unverified: tuple[Unverified, ...] = ()  # leads, never scored
    reason: str = ""  # populated when status is not OK
    detail: Mapping[str, Any] = field(default_factory=dict)
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


---

## Probe 3 — Ground Truth Rejected

> Will this verifier reject the taskset's own declared answer?

The rejection half of the gap. `weak_oracle` asks whether a verifier accepts work
that is wrong; this asks whether it rejects work that is right. Both are the same
failure of a reward signal, and the second is not the lesser one — a verifier that
rejects correct answers trains a model *away* from correct behaviour, because the
gradient says the right answer was wrong.

It submits the task's declared answer, rendered every way
[`bohrin.relations`](../src/bohrin/relations/) certifies as meaning-preserving, and
reports tasks where the verifier accepted none of them.

### Why it carries no weight in the Verification Gap

Its `weight` is `0.0`. That is a soundness argument, not caution: **three
situations produce an identical result**, and only the first is a defect.

| What happened | Example | Defect? |
|---|---|---|
| The comparison is broken and correct answers are discarded | — | **yes** |
| The verifier enforces an output contract the prompt documents | `reverse_text` requires `<reversed_text>` tags and stores the bare reversal | no |
| The reward never reads the reply | `code_golf` scores `trace.metrics.get("passed")`, set elsewhere in the episode | no |

Both confounds were found by running this probe over the public `verifiers`
corpus, not predicted in advance. A score pooling all three would report a
correct verifier as defective, which the governing rule forbids outright. So the
finding is reported for a human to judge and the number stays out of it. When the
gap is split into acceptance and rejection sides, a rejection-side score can carry
this without contaminating the acceptance-side one.

### Wording discipline

Findings report a **search budget**, never a verdict: *"no rendering of the
declared answer was accepted (8 tried)"*. Not *"this verifier rejects correct
answers"* — the catalogue is finite, and the ninth rendering might have passed.
This is the same discipline `determinism` follows when it quotes detection power
instead of claiming determinism.
