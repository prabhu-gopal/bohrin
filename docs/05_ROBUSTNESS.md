# Known weaknesses

What the current implementation does not handle, why, and what would fix it.

This exists because the alternative is discovering these in front of a customer. Each
entry names the evidence, not just an opinion.

---

## Fixed, recorded here because the reasoning generalises

### Redundant candidates were being submitted twice

`empty_body` emitted `""` and a whitespace-only reply. Every verifier strips, so both are
the *same submission* — one scoring call spent for no information.

Redundant mutants are a documented validity threat in the mutation-testing literature
(equivalent mutants alone are measured at 4–39% of all mutants in real software). Here the
cost is not only statistical: each duplicate is a real call against someone else's
environment.

**Fixed:** candidates whose payload is identical after stripping are submitted once.

### The taskset was read through the wrong hook

The adapter called `Taskset.load()`. Upstream is explicit that `load` is the subclass hook
that *builds* tasks, and that `__iter__` is the read path — `head`/`shuffle` views and the
config-layer system prompt are applied there. Calling `load` directly discarded both.

The loud symptom was that `--max-tasks` stopped bounding anything, so auditing
`color_codeword` — an `INFINITE` taskset — ran past ten minutes with no output and growing
memory, because the probes materialise the task list before scoring. The quiet symptom was
worse: a taskset configured with a system prompt was audited without it, which is a
different task from the one the customer runs, and nothing in the report said so.

**Fixed:** the adapter iterates the taskset, and a taskset still marked infinite after any
`--max-tasks` bound is refused with a message naming the flag.

The reasoning that generalises: **when integrating a library, the hook you override is
rarely the entry point you call.** This was found by running the tool against a real
environment, not by the test suite — the seventh defect in this project found that way and
the first that could not fail, only hang.

---

## Open — ranked by how likely they are to matter

### 0. Recall is bounded by six fixed operators, and now measurably so

The open probes carry six deterministic, model-free operators. A sweep of six `verifiers`
v1 environments puts a number on what that buys:

| Environment | Result |
|---|---|
| `scratchpad` | **gap 50/100** — 8 of 8 tasks accept a prompt echo |
| `glossary` | 0/100 at full coverage |
| `proposer_solver` | 0/100 at full coverage |
| `color_codeword` | 0/100 at full coverage |
| `reverse_text` | weak_oracle declined — no rendering of the reference passes its own verifier |
| `gsm8k` | not measured — the reward needs a runtime |

One defect found, zero false accusations. But two of the three clean results are a limit of
the operators, not a verdict on the grader: `glossary` scores `answer.lower() in reply`, and
`proposer_solver` scores on the last integer in the reply. Both accept submissions that are
obviously not solutions; no fixed operator here constructs one.

The single hit is instructive about *why* it hit. `scratchpad` grades `self.data.word in
answer` while its own prompt contains `word="alpha"`, so `identity_return` — echo the
prompt — lands. It was found by an operator that ignores the reference entirely, on a task
where no reference was even discovered (`word` is not in the recognised names, see §4).
The yield came from a structural operator, not a differential one.

**Fix:** this is the boundary the proprietary attack engine is for — verifier-aware,
model-generated payloads. What the open core owes in the meantime is to state the boundary,
which `README.md` now does.

### 1. Harness disruption is discarded, not reported

A candidate that **crashes the verifier**, exhausts its memory, or trips its timeout is
currently recorded as an `error` and counted as noise.

Published work on reward-hacking benchmarks treats exactly this as a first-class exploit
category — agents avoid unfavourable scoring by "triggering timeouts, crashing the harness,
exhausting memory or disk" — and scores such attempts fail-closed while still *logging them
as exploit attempts*. Bohrin does the fail-closed half and drops the logging half.

A submission that crashes a grader is a real robustness defect in that grader, and it is
one a customer would want to know about.

**Fix:** a `harness_disruption` finding class, distinct from an acceptance exploit, raised
when a well-formed submission causes the verifier to error or time out. Needs care to
separate a verifier defect from a Bohrin defect — an ordinary string payload should never
crash a well-written reward function, so the burden is on us to keep payloads well-formed.

### 2. The gap pools distinct mechanisms into one number

The literature is explicit that reward hacking covers separable mechanisms — learned-reward
exploitation, test-suite exploitation, execution-environment manipulation, under-investment
in unmeasured quality — and that **these should not be pooled into one rate**.

The Verification Gap is a weighted mean across probes measuring different mechanisms.
Mitigated by the mandatory coverage descriptor and per-probe sub-scores, so the
decomposition is always available and is the actionable part. But the headline number does
pool, and that limitation belongs in the specification rather than in a reader's head.

**Fix:** state it in `02_VERIFICATION_GAP.md`, and lead the report with the per-probe
breakdown rather than the composite where space allows.

### 3. The false-positive rate is unmeasured

Comparable work validates a detector by manually auditing a random sample of flagged and
unflagged runs, and is candid when it has not: *"calibration is an assumption, not a
verified ground truth; a manual audit of a random sample was not performed, and the true
base rate is unknown."*

Bohrin's clean-fixture test proves zero false accusations **on a fixture we wrote**. That is
a guard against regression, not a measurement of the real rate.

The sweep in §0 adds the first real-environment evidence: zero false accusations across six
environments. Six is not a rate. It is worth recording because it is the first time the
precision machinery ran against code nobody here wrote, and worth discounting because a
sample that size would not detect a 10% false-positive rate with any confidence.

**Fix:** the public sweep. Audit real Hub environments, hand-check a random sample of
findings, and publish the measured false-positive rate alongside the index. Until then no
accuracy claim should be made.

### 4. A reference is discovered by name, not by contract

`TaskData` standardises `prompt` and `description` but not a reference solution, so it is
looked up under recognised names (`answer`, `solution`, …) and is `None` otherwise.

Without a reference the differential operators cannot run and no green baseline is
possible, so the task is probed by structural operators alone. This is reported, never
hidden — but it means yield varies with a taskset's naming conventions rather than with
its actual quality.

The sweep in §0 is the first data on this, and it goes against the assumption. `scratchpad`
stores its reference under `word`, which is not a recognised name, so all 8 tasks were
probed with structural operators alone — and that is exactly where the one real finding came
from. `reverse_text` shows the opposite edge: a reference *was* found, but the verifier
wants it inside `<reversed_text>` tags, so no rendering passed and the whole taskset became
unmeasurable for `weak_oracle`. A reference discovered by name is neither necessary for a
finding nor sufficient for a baseline.

**Fix:** measure how often a reference is found across real Hub environments before
investing further. On the evidence so far the differential operators may matter less than
assumed, and a baseline that can learn the required *presentation* from the task prompt
would unlock more than more operators would.

### 5. Determinism cannot see rare flakiness

At the default five repeats, a verifier flipping 5% of the time is missed roughly three
times in four. Reported honestly as detection power, and it remains a real ceiling.

**Fix:** a tiered budget — a small default, a larger one on demand, and the largest for
tasks already suspected. This is the strategy the flaky-test literature recommends after
finding that even a thousand reruns has under a 10% chance of surfacing a flake near 1e-4.

### 6. Isolation is classified, not provided

Bohrin refuses to run unshielded and records the level, but on the offline path the
verifier's reward function still executes in-process when the user accepts that.

**Fix:** a container-backed execution mode, which also unlocks the runtime-dependent
tasks currently refused outright — likely the single largest coverage gain available.

### 7. A verifier could detect it is being audited

Nothing prevents a reward function from recognising Bohrin's candidates and behaving
differently. No evidence this happens today, and it would be self-defeating for an honest
vendor, but a certification product creates the incentive.

**Fix:** not obviously solvable, and worth stating rather than pretending otherwise.
Payload diversity raises the cost; it does not close the hole.
