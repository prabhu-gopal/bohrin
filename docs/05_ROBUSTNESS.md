# Known weaknesses

What the current implementation does not handle, why, and what would fix it.

This exists because the alternative is discovering these in front of a customer. Each
entry names the evidence, not just an opinion.

---

## Fixed, recorded here because the reasoning generalises

### Three operators could report a correct verifier as broken

The governing rule is that Bohrin must never falsely accuse a verifier. Four paths
broke it, and all four shared one root cause: **a difference in source was being
treated as evidence of a difference in behaviour.**

| Path | Trigger |
|---|---|
| `constant_return` | reference `"1.0"`, a correct numeric grader, candidate `"1"` |
| `constant_return` | reference `"true"`, a correct case-folding grader, candidate `"True"` |
| `negate_condition` | a branch whose two arms do the same thing |
| `drop_side_effect` | a reference whose function bodies were already `pass` |

The first is the one that mattered. Numeric answers are the commonest task shape in
the ecosystem, and the result was a Verification Gap of 50/100 against a flawless
grader — the exact failure mode that would end the product's credibility if it
appeared in a published index.

**Why the tests did not catch it.** The clean fixture was an exact-string matcher.
It models a *strict* verifier, and a strict verifier rejects every rendering
difference, so the fixture was structurally incapable of exercising this class. The
missing fixture was a verifier that is **lenient about presentation and still
entirely correct** — the shape most real verifiers actually have.

**Fixed:** `mutate/equivalence.py` adds `provably_distinct` (no ground unless the
payloads differ under every normalisation a correct verifier might apply) and
`code_equivalent` (Trivial Compiler Equivalence on Python bytecode). `negate_condition`
now carries no ground at all, because TCE cannot help it: an inert negation compiles
differently precisely because the source differs. `tests/_fixtures.py` gains a table of
lenient-but-correct graders, and every registered operator is run against every one of
them.

The reasoning that generalises, twice over:

1. **A clean fixture only guards the failures it can express.** Zero findings on a
   fixture that cannot produce the failure is not evidence of anything. Ours proved
   only that we do not accuse *strict* verifiers.
2. **Verify a guard by removing it.** Each of the four fixes was reverted in turn to
   confirm the suite went red. Three reverts were initially silent — one because a
   defence-in-depth check covered for the other, and one because the test graded with
   a substring matcher that rejected the mutant before the ground was ever consulted.
   A test that cannot fail is not protecting anything.

### The equivalence guard suppressed candidates on bare-answer references

Python discards a bare constant expression statement as dead code, so `compile("70")` is
byte-identical to `compile("")`. Trivial Compiler Equivalence therefore judged an empty
submission to be "the same program as the reference" and dropped it before it reached the
verifier — on every task whose answer is a bare number, which is the commonest shape in the
ecosystem.

**Fixed:** TCE declines to apply when the reference does not compile to a program that does
anything. It still catches what it was built for, and it cannot reintroduce a false
accusation, because the un-suppressed candidates carry independent grounds.

Two things generalise:

1. **A guard is a change to recall as well as to precision, and only one of those fails
   loudly.** A false accusation is visible in a report. A wrongly suppressed candidate is
   visible nowhere — nothing errors and nothing is printed. Every suppression added here
   now needs a test asserting the thing it must *not* suppress.
2. **Found because a test failed for the wrong reason.** It surfaced while writing an
   unrelated harness-disruption test that would not fire; the tempting move was to adjust
   the fixture until it passed, and the fixture was correct. The check was wrong.

### A taskset with no reward function was reported as clean

A task carrying no reward hook has no verifier. Everything submitted to it scores zero, so
everything is "rejected", so no candidate is ever a finding — and the audit reported
`0 / 100` at `coverage: 2 of 2 probes`. The strongest claim the tool can make, arrived at
by measuring nothing, and `--fail-on-gap` passed it.

**Five of the eighteen loadable environments in the public `verifiers` repository** —
`wordle`, `kuhn_poker`, `openenv_wordle`, `proposer_solver`, `wiki_search` — enumerate such
tasks, because they are judged cross-agent, at the episode level, or by a seat minted only
once a model has run. All five reported a clean sweep.

**Fixed:** both probes refuse a task with no reward hook and say why. Those environments now
report `not measured` at `coverage: 0 of 2`, and a CI gate exits 3 rather than 0.

The reasoning that generalises: **check that the thing you are measuring exists before
reporting the measurement.** Every guard in this codebase asks whether a finding is
justified; none asked whether a *null* finding was. A null result inherits all the
authority of the method and none of its checks.

It also changes the corpus arithmetic honestly. Of 19 public environments: 1 fails to load,
9 cannot be measured, 6 are genuinely clean, and 2 carry real findings. The finding rate is
therefore **2 of 8 measurable environments (25%)**, not 2 of 19 (10%) — the denominator that
matters is what could actually be examined.

### A taskset that failed to load escaped as a traceback

Loading a taskset imports the customer's package and runs its module-level code, so it can
raise anything. Only `ModuleNotFoundError` was handled; everything else escaped the CLI's
user-error set as a raw Python stack trace with exit 1.

Found by running the tool against a taskset written for a slightly different `verifiers`
API (`import verifiers as vf` rather than `verifiers.v1`) — the first thing tried, not a
constructed edge case. `verifiers` is pre-1.0, so version drift is the normal condition.

**Why it matters more than a cosmetic bug.** A stack trace reads as *Bohrin crashed* when
the truth is *your taskset did not load*. That is the blame inversion this project exists
to avoid, and it undoes the impression every other carefully worded error path builds.

**Fixed:** `TasksetLoadError` names the taskset, quotes the underlying error, states the
fault is not Bohrin's, and exits 2. The original exception stays chained.

The reasoning that generalises: **at a boundary where foreign code runs, the exception
type is not knowable — only the boundary is.** Enumerating expected exception types there
fails open into a traceback; catching broadly and re-raising as a domain error fails closed
into a message.

### An audit could not fail a CI job

Every completed audit returned 0. An audit reporting 20 exploits at a gap of 50 was
indistinguishable, to a pipeline, from a clean one.

**Fixed:** opt-in `--fail-on-finding` and `--fail-on-gap SCORE`, with the exit-code
contract in `--help`. The design point is **exit 3**: a gate can pass because nothing was
*found* or because nothing was *measured*, and folding those together is how a tool
reports a false green. `code_golf` — every task needs a runtime — exits 3, not 0.

This is the coverage descriptor's logic applied to the exit code, and it is the same
distinction SARIF draws with `invocation.executionSuccessful`.

### A clean score implied more than it had measured

`glossary` scores 0/100 and grades by substring containment; `proposer_solver` scores
0/100 and grades on the last integer in a reply. Both are exploitable. The report said
`0 / 100 · coverage: 2 of 2 probes` and nothing else, and a reasonable reader concludes
their verifier is sound.

§0 below had always said so. The report had not — and the report is what people read.

> **Update, 1.2.** Both examples here have since been resolved, and the caveat's wording
> had not kept up. `glossary` is caught by `false_negation` (1.1.0), and `proposer_solver`
> attaches no reward function to its tasks and now reports as unmeasured rather than clean.
> Measured against synthetic graders of each shape, substring, first-number and
> last-number graders are all caught. The caveat named them anyway until 1.2, while saying
> nothing of the blind spot that does exist — a grader reading only one answer format, such
> as the last `\boxed{}`, which rejects every payload on format and reads clean whether or
> not it is weak. The caveat now names that instead.

**Fixed:** a clean score carries a line naming how many operators were tried and what a
clean result bounds.

The reasoning that generalises: **a false reassurance is a false accusation pointed the
other way.** The governing rule forbids reporting a correct verifier as broken; reporting
an unmeasured verifier as clean is the same error, and for a certification product it is
the more expensive one.

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

Re-measured cold against all 19 published environments (fresh clone, fresh venv): 12
measured at full coverage, 7 refused, **two defects found, zero false accusations**. The
second is `deepwiki` at 25/100 — its reward is `answer.lower() in reply.lower()` with
`answer="python"`, and its prompt names the repo `modelcontextprotocol/python-sdk`, so
echoing the prompt scores full marks without ever calling the tool the task exists to
exercise. Confirmed independently with Bohrin out of the loop.

That is now **two independent real environments with the same root cause: the answer is
sitting in the prompt.** A pattern with two data points, not an anecdote — and the
strongest available argument for a dedicated answer-leakage check.

One defect found, zero false accusations. But two of the three clean results are a limit of
the operators, not a verdict on the grader: `glossary` scores `answer.lower() in reply`, and
`proposer_solver` scores on the last integer in the reply. Both accept submissions that are
obviously not solutions; no fixed operator here constructs one. *(Superseded: `glossary` is
caught by `false_negation` from 1.1.0, and `proposer_solver` was later found to attach no
reward function to its tasks — see the 1.2 update above.)*

The single hit is instructive about *why* it hit. `scratchpad` grades `self.data.word in
answer` while its own prompt contains `word="alpha"`, so `identity_return` — echo the
prompt — lands. It was found by an operator that ignores the reference entirely, on a task
where no reference was even discovered (`word` is not in the recognised names, see §5).
The yield came from a structural operator, not a differential one.

**Fix:** this is the boundary the proprietary attack engine is for — verifier-aware,
model-generated payloads. What the open core owes in the meantime is to state the boundary,
which `README.md` now does.

### 1. Seven of nineteen real environments cannot be audited

Measured across the full published `verifiers` set: 37% are refused rather than scored.
Four distinct causes, needing four different fixes.

| Cause | Environments | What would fix it |
|---|---|---|
| Reward needs a runtime | `code_golf`, `gsm8k`, `bash_interception`, `wiki_search` | Container-backed execution (§7) |
| Reference fails its own verifier | `reverse_text` | A baseline that learns required *presentation* from the prompt |
| No adapter recognises it | `compact` | Adapter coverage |
| Upstream API drift | `nemo_gym_weather` | Version-tolerant adapter |

Refusing is the correct behaviour — each is reported, never scored as clean — but coverage
this narrow bounds how useful the tool is regardless of how sound it is. Container
execution alone converts four of the seven, which makes it the single highest-value item
open.

### 2. Harness disruption — now reported, and firing nowhere yet

A candidate that **crashes the verifier**, exhausts its memory, or trips its timeout is
currently recorded as an `error` and counted as noise.

Published work on reward-hacking benchmarks treats exactly this as a first-class exploit
category — agents avoid unfavourable scoring by "triggering timeouts, crashing the harness,
exhausting memory or disk" — and scores such attempts fail-closed while still *logging them
as exploit attempts*. Bohrin does the fail-closed half and drops the logging half.

A submission that crashes a grader is a real robustness defect in that grader, and it is
one a customer would want to know about.

**Fixed.** A `HarnessDisruption` finding class, distinct from an acceptance exploit and
carrying no ground, is raised when a well-formed submission makes the verifier fail. It is
excluded from the `weak_oracle` sub-score, because nothing was accepted and a crash must
not read as the verifier rewarding wrong work.

Separating a verifier defect from ours is handled by a guard rather than by care: a
disruption is only reported for a task where **another candidate scored successfully**. A
task where everything failed is environmental — possibly our own bug — and is reported as
unmeasurable instead.

**It fires nowhere on the current corpus.** Every environment was probed with an empty
reply, a plain refusal, a 100 KB payload and a heavy-emoji payload; no reward function
raised. The two errors seen are Bohrin's own runtime refusal (`bash_interception`) and
upstream API drift (`nemo_gym_weather`), neither triggered by a payload. Reported here
rather than counted as yield — the check exists because a customer's private taskset is
not one we have tested.

### 3. The gap pools distinct mechanisms into one number

The literature is explicit that reward hacking covers separable mechanisms — learned-reward
exploitation, test-suite exploitation, execution-environment manipulation, under-investment
in unmeasured quality — and that **these should not be pooled into one rate**.

The Verification Gap is a weighted mean across probes measuring different mechanisms.
Mitigated by the mandatory coverage descriptor and per-probe sub-scores, so the
decomposition is always available and is the actionable part. But the headline number does
pool, and that limitation belongs in the specification rather than in a reader's head.

**Fix:** state it in `02_VERIFICATION_GAP.md`, and lead the report with the per-probe
breakdown rather than the composite where space allows.

### 4. The false-positive rate is unmeasured

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

### 5. A reference is discovered by name, then by contract — and still missing for some

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

**Partly fixed.** A reference is now also read from the field the reward function itself
consults, parsed from its source rather than pattern-matched. `scratchpad` gains its
reference (`word`) this way. Three environments — `interception`, `grayscale_interception`,
`web_search_interception` — expose no non-standard field at all, so no discovery strategy
can help them; `alphabet_sort` buries its expected turns inside an `info` dict, which has
no single submission form. The remaining limit is real but smaller than assumed.

**Fix:** measure how often a reference is found across real Hub environments before
investing further. On the evidence so far the differential operators may matter less than
assumed, and a baseline that can learn the required *presentation* from the task prompt
would unlock more than more operators would.

### 6. Determinism cannot see rare flakiness

At the default five repeats, a verifier flipping 5% of the time is missed roughly three
times in four. Reported honestly as detection power, and it remains a real ceiling.

**Fix:** a tiered budget — a small default, a larger one on demand, and the largest for
tasks already suspected. This is the strategy the flaky-test literature recommends after
finding that even a thousand reruns has under a 10% chance of surfacing a flake near 1e-4.

### 7. Isolation is classified, not provided

Bohrin refuses to run unshielded and records the level, but on the offline path the
verifier's reward function still executes in-process when the user accepts that.

**Fix:** a container-backed execution mode, which also unlocks the runtime-dependent
tasks currently refused outright — likely the single largest coverage gain available.

### 8. A verifier could detect it is being audited

Nothing prevents a reward function from recognising Bohrin's candidates and behaving
differently. No evidence this happens today, and it would be self-defeating for an honest
vendor, but a certification product creates the incentive.

**Fix:** not obviously solvable, and worth stating rather than pretending otherwise.
Payload diversity raises the cost; it does not close the hole.
