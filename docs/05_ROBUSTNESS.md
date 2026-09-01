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

---

## Open — ranked by how likely they are to matter

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

**Fix:** measure how often a reference is found across real Hub environments before
investing further. If it is rare, the differential operators matter far less than assumed.

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
