# What is released, and what v0.1 must do

## The boundary

**Public = how to test. Proprietary = what to try.**

| Component | Status | Reasoning |
|---|---|---|
| Probe framework and contract | **Open** | Adoption surface; carries no attack content |
| Verification Gap spec + reference implementation | **Open** | A metric only the vendor can compute is a sales qualifier, not a standard — and reproducibility substitutes for accreditation |
| `weak_oracle` probe | **Open** | Its yield depends on attack content, which is withheld |
| `determinism` probe | **Open** | Universal — needs no rubric structure or reference solution; cannot false-accuse |
| Baseline mutation operators | **Open** | Published, mechanical techniques; withholding them buys nothing |
| Report renderer (tty / html / json) | **Open** | Distribution — the artifact gets forwarded to third parties |
| `verifiers` + OpenEnv adapters | **Open** | Standard-native; makes the installed base addressable |
| Adversarial attack engine | **Closed** | The operative capability, and dual-use |
| Maintained attack library | **Closed** | Refreshed against each model generation — the subscription |
| Probes 3–6 | **Closed** | Held as options; openable later, never recallable |
| `fix` — gated remediation | **Closed** | Requires knowing which assertion closes which exploit |
| Certification service | **Closed** | Structurally impossible to self-issue |
| Hosted CI, history, rollout API | **Closed** | Operated infrastructure |

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

## v0.1 — definition of done

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

### Explicitly out of scope for v0.1

- HTML report — `--json` and the terminal carry v0.1
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

Run the two open probes across a large sample of public environments on the
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

## Open questions for approval

1. ~~Package name.~~ **Decided: keep `bohrin`, yank the old releases.** The name
   belongs to this product. PyPI *deletion* is still permitted (PEP 763, which
   would have imposed a 72-hour deletion window, was withdrawn in September 2025)
   — but deleting is the wrong instrument: it releases the name for anyone to
   claim, creating a window in which the project could be taken and used for
   dependency confusion. Yanking is reversible, keeps ownership, and marks
   0.1.0/0.2.0 as do-not-install. The old tool lives on as `adduct`, already
   published. The new tool ships at **1.0.0** to make the discontinuity
   unmistakable rather than looking like an upgrade of the analyzer.

2. **Repo reuse.** This repo's history is the dataset analyzer's. Keep the history
   or start clean? The code is preserved in the `adduct` repo and on PyPI either
   way.
3. ~~Composition probe applicability.~~ **Resolved by measurement.** Sampling the
   public `research-environments` catalogue found 6 of 7 environments have exactly
   one reward function, so composition would never run. It is replaced by
   `determinism`. See [03_PROBES.md](03_PROBES.md#why-not-composition).
