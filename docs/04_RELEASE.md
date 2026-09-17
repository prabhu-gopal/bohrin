# What is released, and what 1.0.0 shipped

## The boundary

**Open: one complete job. Paid: different jobs.**

The job Bohrin does completely, for free, forever:

> **Check a grader you own, on your machine.** No account, no upload, no part of that job
> held back, and no check that exists only in a paid tier.

What is sold is not more of that job. It is different jobs: searching a grader for cheats a
fixed list cannot construct, watching a training run, reaching into systems Bohrin does not
run, holding a risky action before it happens, remembering history across a team, and issuing
a certificate an outsider can rely on.

| Component | Status | Reasoning |
|---|---|---|
| The engine: loading a target, building evidence, proof rules, scoring, reporting | **Open** | An auditor nobody can inspect is not believed |
| Probes: `weak_oracle`, `determinism`, `ground_truth_rejected`, `answer_leakage` | **Open** | Fixed, model-free checks built on published techniques; see [03_PROBES.md](03_PROBES.md) |
| Mutation operators (nine) and answer relations (seventeen) | **Open** | Published, mechanical techniques; withholding them buys nothing |
| Verification Gap spec + reference implementation | **Open** | A metric only the vendor can compute is a sales qualifier, not a standard |
| Adapters: `verifiers` (`load_environment` and v1) and Inspect | **Open** | Adapters are doors into a workflow, not a moat |
| Report format, `--json`, exit codes, CI gating | **Open** | The report gets forwarded to third parties; a program must read everything a person can see |
| Checks that read only what you already have locally — version history, a trace file on disk | **Open** when they land | Same job, same machine, no connector and no account |
| The accuracy method: how precision is measured and how a published finding is re-run | **Open** | Independence means the method is checkable |
| Certificate format and the verifier for it | **Open** when it lands | A buyer must be able to check a certificate without trusting a website |
| Adaptive, model-driven search for cheats a fixed check cannot construct | **Closed** | Costs inference on every run, improves continuously, and is dual-use |
| The maintained exploit library and trained detectors | **Closed** | Refreshed against each model generation; the compounding asset |
| Connectors into systems Bohrin does not run — payments, ticketing, CRM, production databases | **Closed** | Operational reach and operational liability |
| Holding a risky action at runtime: policy, approvals, audit trail | **Closed** | A different job from checking a grader |
| Cause finding and regression history across a team, at scale | **Closed** | Operated infrastructure |
| Automated remediation | **Closed** | Easy to get wrong; it is a different job |
| Certificate issuance | **Closed** | Structurally impossible to self-issue |

### What this means in practice

- **Nothing released as open is ever withdrawn.** Not a check, not an adapter, not a format.
- **No nag inside the free job.** No upload, no account prompt, and never a message saying a
  finding is withheld. Anything paid is a different command or a clearly marked deeper search,
  never a locked line in a result you already have.
- **The open check set grows.** New fixed, model-free checks are welcome here, including checks
  that read version history or a trace file from disk, because they are part of the same job.
- **Optional telemetry stays optional.** There is none today; if it ever exists it is off by
  default and documented.

Two independent arguments produce this same line: distribution (a gated
standard is not a standard) and certification credibility (an unauditable
method is not an attestation). When two unrelated lines of reasoning converge,
the boundary is probably right.

### Irreversibility

Opening later is cheap and well received. Closing later is not — the documented
precedent is a static-analysis vendor that restricted an already-open licence and
was forked by a coalition of competitors within four weeks, with the fork
retaining recognition.

Therefore:

- The attack engine is **proprietary from commit #1**. Never published, never
  subsequently restricted.
- Probes 3–6 are withheld not because a paywall protects published techniques,
  but because they can be released later and cannot be recalled. They are
  options, spent deliberately.
- **Apache 2.0**, decided once. The resale threat that motivates AGPL or BSL is
  weak here: the harness is of limited use without withheld attack content, and
  an attestation's value cannot be assumed by whoever runs copied code. A
  source-available licence would additionally undermine the transparency the
  certificate depends on.
- **Register the trademark before public launch.** A permissive licence lets
  anyone fork and relicense; the one thing they cannot do is use the name.
  Trademark is the only asset that survives a fork, and registering after one is
  materially harder.

### Contributions

DCO, not a CLA — consistent with the previous codebase. A CLA signals exactly the
intent that makes engineers distrust open-core vendors, and the proprietary value
will never originate in an unsolicited pull request.

The constraint this imposes is real and accepted: **externally contributed code
cannot be moved into proprietary components.** Contribution surface is therefore
adapters and operators; the metric definition and scoring are not, because their
stability is what makes the number citable.

---

## 1.0.0 — definition of done (met)

The release is not "the framework exists". It is a single sentence:

> A stranger runs `pip install bohrin && bohrin audit <taskset>` against a real
> public environment and gets a Verification Gap with reproducible evidence, in
> **under 15 minutes from cold**.

That threshold is the published benchmark for developer-tool time-to-first-value,
and everything below is scoped to protect it.

### In scope

- `verifiers` v1 adapter — `detect()`, task enumeration, `score()` via direct
  reward invocation on a constructed `Trace`
- `weak_oracle` with the baseline operators and **wrongness establishment**
- `determinism` with serial repeats (concurrent mode behind a flag)
- Verification Gap with the mandatory coverage descriptor
- `bohrin audit` (tty + `--json`), `bohrin list-probes`, `bohrin explain <id>`
- Isolation detection with refusal; `docker` default
- Fault-injection **and clean-fixture** test suites, both CI-enforced

### What 1.0.0 got wrong about its own definition of done

The sentence above says "reproducible evidence". 1.0.0 did not literally meet it: every
finding printed `bohrin audit --task N --operator X`, and neither flag existed, so the
command a reader would paste exited with `unrecognized arguments`. Two further first-run
defects sat on the same path — a taskset that generates tasks forever hung the audit with
no output instead of honouring `--max-tasks`, and a missing extra was reported *after* the
isolation refusal, so the first thing a new user was told to fix could not have helped.

All three are fixed in 1.0.1, and all three were found by running the published tool
against real public environments rather than by the test suite. The definition of done was
right; the check that it had been met was missing. Every one now has a test that would
have caught it.

### Explicitly out of scope for 1.0.0

- HTML report — `--json` and the terminal carry 1.0.0
- OpenEnv adapter — one adapter, done properly, beats two done partially
- Any entitlement, licensing, or billing machinery
- Any hosted service

### Non-negotiables

1. **Zero false accusations on the clean fixture.** Build-breaking.
2. **The gap never prints without coverage.**
3. **The public package never references a proprietary package.** The dependency
   arrow points one way; the open client must be fully functional and testable
   with nothing proprietary installed.
4. **`bohrin.probes` is public API.** Renaming it breaks every customer and every
   third-party plugin simultaneously.

---

## The launch mechanism

Not "we built a tool" — **"we measured the public ecosystem, here is what we
found."**

Run the open probes across a large sample of public environments on the
Environments Hub and publish the **Verification Gap Index**: per-environment
scores, method, raw data, reproducible by anyone.

This is the same play the previous codebase ran successfully — a sweep over 20
real public datasets, published with raw results — and it worked. The index is
the credential that substitutes for having no customers, and it doubles as
qualification: it tells you exactly who to talk to, and what their number is,
before you make contact.

### Coordinated disclosure — required, not optional

Publishing defect data about environments other people maintain, and in some
cases sell, without notice would be both discourteous and self-defeating: those
maintainers *are* the customer base.

- Maintainers are notified privately, with reproduction detail, and given a
  defined window to respond before publication.
- Published findings characterise the defect class and its magnitude.
- Environments under active remediation are reported as such, not as unqualified
  failures.
- The index reports on the state of the ecosystem, **not** on the competence of
  individual maintainers, and its framing must say so explicitly.

### Dual-use posture

Bohrin generates working exploits against verifiers. The same artifact that lets
a vendor repair an environment lets a third party defeat one.

The security industry's settled norm is not to withhold the category — major
exploitation frameworks are themselves open — but to bind use to explicit
authorisation from the system owner. Bohrin adopts that: auditing is defined as
an operation performed on an environment you own or are authorised to assess,
stated in the docs and the terms.

This also supplies a second, publicly defensible reason for the attack engine to
be the withheld component: publishing a maintained, current exploit generator for
benchmark verifiers would measurably assist benchmark manipulation. A withholding
argument that does not rest on commercial self-interest is more durable than one
that does.

---

## Decisions already taken, recorded so they are not reopened

1. **Package name.** `bohrin` is kept, and the pre-pivot releases are yanked rather than
   deleted: deleting releases the name for anyone to claim, which invites dependency
   confusion, while yanking keeps ownership and marks `0.1.0`/`0.2.0` as do-not-install. The
   pre-pivot tool lives on as `adduct`. This tool started at **1.0.0** so the discontinuity
   is unmistakable.
2. **Repository history.** Kept. The earlier history belongs to the pre-pivot tool, which is
   preserved in its own repository and on PyPI either way.
3. **Composition as a probe.** Replaced by `determinism`, by measurement: sampling the public
   environments catalogue found 6 of 7 environments have exactly one reward function, so a
   composition check would almost never run. See
   [03_PROBES.md](03_PROBES.md#why-not-composition).
