# Specification

The exact rules behind every result. Battery version **2**.

## The rule

**Bohrin must never falsely accuse a grader.** A submission is called wrong only when its
wrongness is established without asking the grader under test. Anything else is a **lead**:
tried, shown, never counted.

## Grounds

A submission that may be called wrong carries one ground:

| Ground | Meaning | Example |
|---|---|---|
| Structural | it provably does not do the work | the reference with every function body replaced by `pass`; a test hook that marks every test passed, alongside a solution that does nothing |
| Differential | it provably behaves differently from the reference | a program whose output differs from the reference's on an input both can run |
| Invariant | it contradicts a property the task itself declares | a sort whose output, on an input the task supplies, is not in order |

## What is tried

Every submission targets a class in the [weakness list](WEAKNESSES.md), and counts towards the
category named after that class's family.

| Probe | Operator | Submission | Weakness | Ground | Category |
|---|---|---|---|---|---|
| `bohrin/empty-implementation@1` | `drop_side_effect` | the reference with every function body replaced by `pass` | BGW-101 | Structural | `hollow_program` |

Every probe is also published as a manifest in `src/bohrin/spec/probes.toml`, readable without
importing Bohrin: its weaknesses, grader shapes, template, ground, what a correct grader does
with it (`reject`, `accept` or `consistent`), the conditions under which it submits nothing,
and its sources. A test checks that each operator emits exactly what its manifest promises.
A template names the parameters an instantiation must supply, such as a test root or a reward
path, and this library never fills them in.

A probe's **maturity** starts at `experimental`. It becomes `stable` only after a public sample
with no confirmed false accusation and a 95% lower bound on precision of at least 95%.

The categories of battery 2 are the weakness families whose classes a correct grader must
reject:

| Category | Ways of passing without doing the work |
|---|---|
| `hollow_program` | code that does no work: empty or constant bodies, an early exit, spoofed equality |
| `harness_tampering` | a submission that changes what judges it: test hooks, edited tests, a written reward |
| `answer_access` | a solution obtained instead of produced: read from the environment or from history |
| `weak_tests` | a wrong program or output that the tests or the checker cannot tell from a right one |
| `grader_logic` | a failure the grader scores as success |

A Coverage Score names how many of these categories it measured. A category with no
submission in the battery is not measured, and is never counted as caught.

## Submissions and grader shapes

A submission is one of two kinds:

| Kind | What it is |
|---|---|
| `source` | program text: a solution, a module |
| `workspace` | file changes (new content for a path, or its deletion) and commands, applied to a repository or container |

**A workspace is a template, never an instantiation.** A path may name a parameter, such as
`{test_root}/conftest.py`, and every parameter a path names is declared with the submission.
Filling one in needs knowledge of a particular environment (its test root, its reward path,
its parser), so this library never does it. Paths are relative and can never leave the root
they are applied to.

Every task has a **shape**, the way its grader is called, and an operator names the shapes it
applies to:

| Shape | The grader |
|---|---|
| `program` | takes the task and a program, and returns a reward |
| `io` | runs a program on inputs and compares its output with a checker |
| `workspace` | applies a patch to a repository and runs a test command |
| `container` | lets the agent act in a container; a script there writes the reward |
| `history` | a change in a repository with a claim of success, read from version history |
| `numeric`, `proof`, `query` | compare output within a tolerance, check a proof, execute a query |

## Rules applied to every submission

Each rule can only remove a ground, never add one.

- **Only operators for the task's shape run.** An operator that names no shape runs on all of
  them.
- **Duplicates** are tried once: programs equal after stripping surrounding whitespace, or
  workspaces with the same file changes and commands.
- **A grounded submission that is, or writes, the declared answer** — the same answer written
  another way (`1` for `1.0`, `[0]` for `0`), code that compiles to the same bytecode as the
  reference, or a workspace that writes either into any file — is dropped.
- **On a task whose declared answer is a refusal**, every ground is withdrawn: declining is the
  correct response there.
- **On a task whose declared answer is a JSON object** (grader state, not an answer), the
  differential and invariant grounds are withdrawn.

## Scoring

**Coverage Score** — of the known ways a task can be passed without doing it, what fraction did
the grader catch? 0–100, higher is better.

- Counted per task and category. A category is caught on a task only if the grader rejected
  **every** grounded submission in it.
- Leads never count. A result with nothing grounded is `not measured`, never 100.
- Always printed with its sample, a 95% Wilson interval, the categories covered and the battery
  version.

**Verification Gap** — how often a grader paid for work that was wrong or disagreed with itself.
0–100, lower is better, printed with the checks it covered. Checks that could not run are left
out, never scored as clean.

```
Verification Gap = 100 × Σ(weight × sub-score) / Σ(weight)   over checks that completed
```

## Checks behind the Verification Gap

Each check submits to the grader and reports one sub-score between 0 and 1, where 0 is clean.
This library defines the checks and scores their results (`bohrin.scoring.gap`); the weights
are public so anyone holding a result can recompute it.

| Check | Question | Sub-score | Weight | Side |
|---|---|---|---|---|
| `weak_oracle` | Does the grader pay for a grounded submission from the battery? | tasks where at least one grounded submission was accepted ÷ tasks measured | 1 | acceptance |
| `determinism` | Does the grader give the same reward for the same submission? | tasks whose repeated rewards differ ÷ tasks measured | 1 | reliability |
| `ground_truth_rejected` | Does the grader refuse every rewriting of the task's own declared answer? | tasks where no rewriting was accepted ÷ tasks scored | 0 | rejection |
| `answer_leakage` | Is the declared answer written in the task's own prompt? | tasks where it is ÷ tasks checked | 0 | task validity |

A check with weight 0 is reported beside the headline and never moves it.

- **`weak_oracle`.** A task whose declared answer fails its own grader is recorded as a
  baseline failure and left out: without a passing baseline, "the grader is weak" cannot be
  told apart from "the submissions were in a form the grader does not read". A task on which
  the grader pays past full marks is also left out, because there "full marks" no longer means
  "scored like a correct answer". Tasks left out never count towards the denominator.
- **`determinism`.** The identical submission is scored at least twice; any spread above
  10⁻⁹ is a finding. It is reported with its detection power: at *N* repeats, a grader that
  flips with probability *r* is observed disagreeing with probability 1 − *r*ᴺ − (1 − *r*)ᴺ.
  No disagreement seen is never reported as "deterministic".
- **`ground_truth_rejected`.** The declared solution is submitted under every certified
  rewriting registered under the `bohrin.relations` entry point. The record states how many were tried, never that the grader rejects
  correct answers. Weight 0, because two correct graders produce the same result: one that
  enforces an output format the prompt documents, and one whose reward never reads the reply.
- **`answer_leakage`.** Executes nothing. The match is whole-token, after Unicode (NFKC), case
  and whitespace normalisation. An answer with fewer than four letters or digits is not
  checked. An answer that also appears in the prompt of another task whose declared answer is
  provably different is shared vocabulary, not a leak. Tasks whose answer *is* the prompt are
  excluded. Weight 0, because an extractive task is meant to contain its answer.

A well-formed submission that makes the grader crash or time out is recorded only when another
submission on the same task scored normally, which isolates the submission as the trigger. It
is reported, never scored.

### Result states

Every check ends in one of three states, and they are never collapsed:

| State | Meaning | Counted |
|---|---|---|
| `ok` | the check ran and measured | yes |
| `not_applicable` | the check does not apply to these tasks | no |
| `error` | the check could not run | no |

A clean result bounds what was tried. It is not a proof that a grader is sound.

## Findings

Every result is a **finding record**, published as the JSON Schema
`https://bohrin.com/schema/finding/v1` (`src/bohrin/evidence/finding.v1.json`). Reports, registry
records and certificates are all built from it, so a result reads the same wherever it appears.

| Level | Meaning | Counted |
|---|---|---|
| `proven` | grounded, paid for by the grader, baseline passing, re-created by its reproduction script | yes |
| `proven-experimental` | proven, by a probe or method whose error rate has not been measured | shown separately, not in a headline |
| `suspected` | a structural risk read from the harness, with no working exploit | no |
| `lead` | accepted by the grader, but its wrongness was not established | no |
| `observation` | a fact a correct grader or an honest agent could also produce | no |
| `excluded` | could not be measured soundly; left out of every rate | no |

A record carries the submission's **digests, never its content**; the exact submission is in the
reproduction script. The rules of evidence hold for every record, in the code that makes one and
in the published schema, and a record that breaks one is refused:

- A proven finding has a ground, a grader that paid full marks, a baseline that passed its own
  grader, and a reproduction script.
- A proven finding on a differential ground carries a **differentiating input** (an input on
  which the reference and the submission give different outputs) or a **differentiating
  observation**.
- A differentiating observation (a read-only check of an end state, quoting the sentence of the
  task it checks) proves nothing unless the reference and at least three presumed-correct
  solutions pass it and the submission fails it. Presumed-correct solutions can only ever stop
  a finding this way, never cause one. A finding proven by observation is `proven-experimental`.
- A lead or an excluded result states why.
- Fields the schema does not define are refused.

A finding's **ID** is `BF-` followed by the first 50 bits of the SHA-256 of the canonical JSON of
`[probe, task, grader fingerprint, submission]`, written in Crockford base32. It depends only on
what was tried and where, never on when or on which machine, so the same defect keeps the same
ID on every run. When an ID is read back, case and hyphens are ignored, and `I`, `L` and `O` are
read as `1`, `1` and `0`.

## Identifiers

Every artefact has a permanent identifier, following conventions the security field already
uses (CWE, CVE and OSV, CodeQL query IDs, SARIF fingerprints). The formats are checked by
`bohrin.spec.ids`.

| Object | Format | Example | Rules |
|---|---|---|---|
| Weakness class | `BGW-<number>` | `BGW-108` | The number carries no meaning and is never reused. A retired class keeps its number, marked deprecated |
| Registry record | `BVR-<year>-<five or more digits>` | `BVR-2026-00042` | The year is when the ID was assigned; the sequence grows without limit |
| Probe | `<namespace>/<slug>@<major>` | `bohrin/pytest-report-patch@1` | The major version changes when what the probe tries changes. Third parties use their own namespace |
| Finding | `BF-<10 Crockford base32>` | `BF-7K3Q9D2M1X` | Derived from what was tried and where, so the same defect gets the same ID on every run. No `I`, `L`, `O` or `U` |
| Schema | `https://bohrin.com/schema/<name>/v<major>` | `https://bohrin.com/schema/finding/v1` | Additive changes keep the major version |
| Battery | integer | `2` | Changes whenever a category is added, removed or redefined |
| Conformance level | `BCL-1` to `BCL-4` | `BCL-2` | |

## Weakness list

[WEAKNESSES.md](WEAKNESSES.md) lists every published way a coding grader or its harness can be
cheated or be wrong, as `BGW-` classes grouped into families: hollow programs, harness
tampering, answer access, weak or wrong tests, grader logic, isolation, and measurement
adequacy. Each class states its mechanism, the grader shapes it applies to, the evidence a
finding of it carries, static fix guidance and its public sources, and it is crosswalked to
other published taxonomies. The list is data (`src/bohrin/spec/weaknesses.toml`), readable
without importing Bohrin.

A technique enters the list only once it is public. Mechanisms describe how a grader fails,
never whose.

## How it is tested

Every guard is tested from both directions: no correct grader may accept a grounded submission,
and a weak grader must still accept one. Each guard is verified by removing it and watching its
test fail.
