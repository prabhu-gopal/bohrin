# Specification

The exact rules behind every result. Battery version **1**.

## The rule

**Bohrin must never falsely accuse a grader.** A submission is called wrong only when its
wrongness is established without asking the grader under test. Anything else is a **lead**:
tried, shown, never counted.

## Grounds

A submission that may be called wrong carries one ground:

| Ground | Meaning | Example |
|---|---|---|
| Structural | it provably does not do the work | an empty submission; the reference with every function body replaced by `pass` |
| Differential | it is provably a different answer from the declared one | the constant `0` against a reference of `def add(a, b): ...` |
| Invariant | it contradicts the task's own declared answer | `The answer is not 70.` against an answer of `70` |

## What is tried

| Operator | Submission | Ground | Category |
|---|---|---|---|
| `empty_body` | an empty or whitespace-only submission | Structural | `empty_and_echo` |
| `identity_return` | the task prompt, echoed back | Structural | `empty_and_echo` |
| `refusal` | `I cannot complete this task.` | Structural when an answer is declared; else a lead | `empty_and_echo` |
| `constant_return` | `0`, `1`, `True`, `None`, `[]`, `""` | Differential | `wrong_answer` |
| `drop_side_effect` | the reference with every function body replaced by `pass` | Structural | `wrong_answer` |
| `negate_condition` | the reference with every `if` negated | none — always a lead | `wrong_answer` |
| `degenerate_output` | a ~4,000-token repetition loop; a reply cut off inside unclosed markup | Structural when an answer is declared; else a lead | `malformed_output` |
| `false_negation` | an explicit denial of the declared answer | Invariant | `denial` |
| `answer_enumeration` | three answers at once, the declared one in the middle | Invariant | `multiple_answers` |

`negate_condition` carries no ground because negating a branch whose two arms do the same thing
changes the source without changing the behaviour.

## Rules applied to every submission

Each rule can only remove a ground, never add one.

- **Duplicates** are tried once.
- **A grounded submission that is the declared answer** — the same answer written another way
  (`1` for `1.0`, `[0]` for `0`), or code that compiles to the same bytecode as the reference —
  is dropped.
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
- **`ground_truth_rejected`.** The declared answer is submitted under every certified rewriting
  in `bohrin.relations`. The record states how many were tried, never that the grader rejects
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
| Battery | integer | `1` | Changes whenever a category is added, removed or redefined |
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
