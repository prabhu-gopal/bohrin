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

### Positive controls: correct work a grader must accept

A grader tightened to stop cheating is exactly the kind that starts rejecting correct code, so the
battery also submits correct programs: the reference, and rewritings of it that are **proved**,
by machine, to do the same thing. A rewriting that cannot be proved is not submitted.

| Probe | Relation | Submission | Proved by | Weakness |
|---|---|---|---|---|
| `bohrin/oracle@1` | `oracle` | the reference, unchanged: the baseline | identity | BGW-124 |
| `bohrin/comment-free-oracle@1` | `comment_free` | the reference with its comments removed | the same syntax tree | BGW-120 |
| `bohrin/reformatted-oracle@1` | `reformatted` | the reference re-laid out by Python's own unparser | the same syntax tree | BGW-120 |
| `bohrin/renamed-oracle@1` | `renamed_locals` | the reference with local variables renamed; never parameters or function names | the same bytecode, up to the names of locals | BGW-120 |

- **If the grader rejects the baseline**, the task is a baseline failure: excluded from every
  rate, never scored.
- **Renaming is refused** in a function that reads its own local names at run time (`locals()`,
  `vars()`, `eval`, `exec`, frame introspection), because bytecode cannot see that; also in one
  with nested scopes, imports, `match`, `global` or `nonlocal`.
- **A rewriting identical to another**, or to the reference once surrounding blank lines are
  ignored, is not submitted twice.
- **Positive controls are never merged with the Coverage Score.** They measure correct-work
  acceptance beside it, so a grader that rejects everything is exposed rather than scoring 100.

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

Each rule can only remove a ground, never add one. Below, the **reference** is the task's
declared solution: a program, for a coding task, or a bare value where a task declares one.

- **Only operators for the task's shape run.** An operator that names no shape runs on all of
  them.
- **Duplicates** are tried once: programs equal after stripping surrounding whitespace, or
  workspaces with the same file changes and commands.
- **A grounded submission that is, or writes, the reference** — code that compiles to the same
  bytecode as the reference, the same value written another way (`1` for `1.0`, `[0]` for `0`),
  or a workspace that writes either into any file — is dropped.
- **On a task whose reference is a refusal**, every ground is withdrawn: declining is the
  correct response there.
- **On a task whose reference is a JSON object** (grader state, not a solution), the
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
| `ground_truth_rejected` | Does the grader refuse every certified rewriting of the task's own reference? | tasks where no rewriting was accepted ÷ tasks scored | 0 | rejection |
| `answer_leakage` | Is the reference written in the task's own prompt (BGW-115)? | tasks where it is ÷ tasks checked | 0 | task validity |

A check with weight 0 is reported beside the headline and never moves it.

- **`weak_oracle`.** A task whose reference fails its own grader is recorded as a
  baseline failure and left out: without a passing baseline, "the grader is weak" cannot be
  told apart from "the submissions were in a form the grader does not read". A task on which
  the grader pays past full marks is also left out, because there "full marks" no longer means
  "scored like a correct solution". Tasks left out never count towards the denominator.
- **`determinism`.** The identical submission is scored at least twice; any spread above
  10⁻⁹ is a finding. It is reported with its detection power: at *N* repeats, a grader that
  flips with probability *r* is observed disagreeing with probability 1 − *r*ᴺ − (1 − *r*)ᴺ.
  No disagreement seen is never reported as "deterministic".
- **`ground_truth_rejected`.** The reference is submitted under every certified rewriting
  registered under the `bohrin.relations` entry point. The record states how many were tried,
  never that the grader rejects correct solutions. Weight 0, because two correct graders
  produce the same result: one that enforces an output format the prompt documents, and one
  whose reward never reads the submission.
- **`answer_leakage`.** Executes nothing. The match is whole-token, after Unicode (NFKC), case
  and whitespace normalisation. A reference with fewer than four letters or digits is not
  checked. A reference that also appears in the prompt of another task whose reference is
  provably different is shared vocabulary, not a leak. Tasks whose reference *is* the prompt
  are excluded. Weight 0, because an extractive task is meant to contain its answer.

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
- Fields the schema does not define are refused, and every field must be exactly the type the
  schema gives it: `"false"` is not `false`, `null` is not an absent field, `NaN` is not a number.
  Text that must say something (a requirement, a reason) may not be only whitespace.

The code that reads a record and the published schema refuse exactly the same records, field by
field; a test breaks every field of a complete record in every way and checks that they agree. A
few rules compare two fields, which JSON Schema cannot express, so only the reader enforces them:
a differentiating input's two outputs must differ, and (for reproduction results) the outcome a
script claims must be the one its runs show.

A finding's **ID** depends only on what was tried and where, never on when or on which machine,
so the same defect keeps the same ID on every run and anyone can recompute it in any language:

1. Take the JSON array `[probe, task ID, grader fingerprint, submission]`, where `submission` is
   the record's `submission` object.
2. Serialise it with the [JSON Canonicalization Scheme (RFC 8785)](https://www.rfc-editor.org/rfc/rfc8785):
   no whitespace, object keys sorted by UTF-16 code units, strings as UTF-8.
3. Take the SHA-256 of those bytes, and its first 50 bits.
4. Write the 50 bits as ten characters of [Crockford base32](https://www.crockford.com/base32.html)
   (`0123456789ABCDEFGHJKMNPQRSTVWXYZ`), five bits each, most significant first, after `BF-`.

For example, probe `bohrin/empty-implementation@1`, task `task-1`, grader fingerprint
`grader-digest` and the source submission `def solve(items):\n    pass\n` give `BF-W6YDC0TBE4`.
When an ID is read back, case and hyphens are ignored, and `I`, `L` and `O` are read as `1`,
`1` and `0`.

## Reproduction scripts

Every proven finding carries a **reproduction script**: plain Python that applies the exact
submission to its reader's own environment, runs their grader and reports what happened. It is
the evidence a stranger actually checks, so its shape is fixed. A complete example, for the
tutorial's grader, is [examples/reproduce_BF-GZW6R2M9CJ.py](examples/reproduce_BF-GZW6R2M9CJ.py).

**The script**

- Is a standalone script with [PEP 723](https://peps.python.org/pep-0723/) inline metadata, so
  `uv run` or `pipx run` can run it as it is. The `script` block declares `requires-python`,
  and a `[tool.bohrin]` table declares `schema = "https://bohrin.com/schema/reproduction/v1"`,
  the `finding` ID, the `probe`, the `submission` digests (as in the finding record) and
  `runs`, at least 3. TOML has no null, so a workspace lists the files it deletes under
  `deleted` instead of giving them a null digest.
- Needs nothing from Bohrin and makes no network call: it imports neither `bohrin` nor any
  networking module.
- Embeds the exact submission, and checks it against the declared digest before running
  anything.
- Runs the grader **exactly as its owner's harness does**, not in a hardened mode, because
  hardening would hide the very defects a tamper probe proves.
- Runs **each grading in its own process, with a time limit**, so that nothing the submission
  does (exit, crash, hang, change global state) can stop the script from reporting or carry
  into the next run. A run that reports no reward counts as not paid: the script fails closed.
- Runs the reference and the submission at least 3 times each.
- Prints one line of JSON last (`https://bohrin.com/schema/reproduction-result/v1`), and exits
  with the code for its outcome:

| Outcome | Exit | Means | The finding becomes |
|---|---|---|---|
| `reproduced` | 0 | the reference passed every run, and the submission was paid full marks every run | unchanged |
| `not-reproduced` | 1 | the reference passed every run, and the submission was never paid | a lead |
| `flaky` | 2 | the grader's verdict varied across runs | a lead |
| `baseline-failed` | 3 | the reference did not pass its own grader | excluded |
| `error` | 4 | the grader could not be run; the result says why | excluded |

**Reading a result.** The reader never trusts the script's own verdict. It recomputes the
outcome from the recorded runs, and refuses a result whose claimed outcome or exit code
disagrees with them, that ran a different submission, or that is about another finding. A
reproduction can take a finding's proof away; it can never give a finding proof it did not
have, and it never changes a finding that was not proven (`bohrin.evidence.reproduction`).

**Why three runs, and why the reference too.** A single passing run cannot tell a defect from a
flaky grader: mature crash reporters do not report a crash they cannot reliably reproduce, and
record how reliably each reproducer triggers
([ClusterFuzz](https://google.github.io/clusterfuzz/using-clusterfuzz/workflows/triaging-new-crashes/),
[syzkaller](https://github.com/google/syzkaller/blob/master/docs/reproducing_crashes.md)).
Running the reference in the same script shows the grader works in the reader's environment, so
a failure to reproduce is never mistaken for a broken setup. When the grader's owner runs the
script, the result is *reproduced* in the sense of
[ACM's artifact review](https://www.acm.org/publications/policies/artifact-review-and-badging-current):
obtained by a different team, using the author's artifact.

Writing a script for a particular environment is up to the tool that found the finding; this
section defines what every such script must be.

## `bohrin power`

Is an evaluation big enough to support what it is used to claim? `bohrin power FILE` reads a
results file a team already has and needs no account and no network. It is arithmetic, so it
cannot accuse anyone; everything it reports is a statistic or a fact about the file.

**The input** is JSON Lines, one object per line (`https://bohrin.com/schema/results-row/v1`):

| Field | Required | Meaning |
|---|---|---|
| `task_id` | yes | the task |
| `model` | yes | the model or configuration scored |
| `score` | yes | the reward, or `null` when the sample errored and got no score |
| `max_score` | no | full marks for the task; default 1 |
| `cluster` | no | tasks that share a source (a repository, a passage) share a cluster |
| `sample` | no | which repeat of the task this is |

Other fields are ignored, so an existing results file can usually be read as it is. A malformed
line is refused with its line number, never skipped.

**What it reports**, for each model and each pair of models:

- **The score with an interval suited to the sample.** Repeated samples of a task are averaged
  first, and scores are scaled by full marks. Pass/fail scores get the Wilson score interval,
  which keeps its coverage on small evaluations where the normal approximation fails
  ([Bowyer et al. 2025](https://arxiv.org/abs/2503.01747)). Other scores get the normal
  approximation, with a note when there are fewer than a few hundred tasks. When tasks come in
  clusters, the standard error is clustered, so related tasks are not counted as independent
  evidence ([Miller 2024](https://arxiv.org/abs/2411.00640), eq. 4).
- **Paired comparisons.** Two models are compared task by task over the tasks both were run on
  (Miller, eq. 7). A difference is called distinguishable only when its whole 95% interval lies
  on one side of zero.
- **The smallest detectable difference**: the true difference found with 80% power at the 5%
  level, `(1.96 + 0.84) × standard error of the difference` (Miller, eq. 10). For one model it
  assumes a second, independent model of similar spread; between two models it is the paired
  figure.
- **An aggregation audit:**
  - errored samples: counted as failures in the headline score, with the score they would give
    if dropped from the denominator shown beside it (BGW-128);
  - scores outside 0 to full marks (BGW-128);
  - tasks one model lacks (BGW-128);
  - the same sample reported twice (BGW-128);
  - partial credit (BGW-122).
- **Whether it is too small** (BGW-133), only when you say what difference you need:
  `--min-difference 0.02`. Without it, size is reported but not judged.

`--json` prints only the report (`https://bohrin.com/schema/power-report/v1`). The exit code is 0
when nothing was found, 1 when the audit found something, 2 when the file cannot be read, and 64
on a usage error.

## `bohrin verify`

What did a change do to the tests and the code, beside what its commits claim? `bohrin verify
--since REF` compares the files at `REF` (default: where the branch started) with the working
tree, uncommitted work included. It needs no account and no network, and it reports **facts**
read from syntax trees, never "cheated": reformatting never looks like a removed assertion, and
a test moved to another file never looks like a deleted one.

| Rule | Reports | Kind | Weakness |
|---|---|---|---|
| `tests-removed` | a test file deleted or emptied, or tests gone, and not moved elsewhere | fact | BGW-109 |
| `check-weakened` | a test's checks dropped from strong (value, error, containment or type) to weak (none, non-None only, truth only, mock calls only, snapshot only) | fact | BGW-109 |
| `checks-removed` | fewer assertions in a test than before | fact | BGW-109 |
| `skips-added` | an unconditional skip or xfail | fact | BGW-109 |
| `conditional-skips-added` | a `skipif`, or a `pytest.skip()` under an `if` | observation | BGW-109 |
| `tolerance-loosened` | a larger `pytest.approx` / `isclose` / `assert_allclose` tolerance, fewer `assertAlmostEqual` places | fact | BGW-134 |
| `timeout-raised` | a larger test timeout | fact | BGW-109 |
| `failure-swallowed` | a check moved inside a `try` whose `except` catches its failure | fact | BGW-109 |
| `expected-value-changed` | the literal a checked expression is compared with changed | observation | BGW-109 |
| `subject-mocked` | a test newly patching the function it is named after | observation | BGW-109 |
| `trivial-checks-added` | a check that cannot fail (`assert True`, `assert x == x` with no call) | observation | BGW-109 |
| `tests-without-checks` | a new test with no assertion | observation | BGW-109 |
| `report-hook-added` | a `conftest.py` hook that can change test outcomes | fact | BGW-108 |
| `selection-changed` | pytest's `addopts`, `testpaths` or other selection settings changed | fact | BGW-109 |
| `replaced-by-stub` | a function that did work replaced by a stub | fact | BGW-101 |
| `always-equal-added` | an `__eq__` that always returns `True` | fact | BGW-103 |
| `timer-reassigned` | `time.perf_counter` or another timer reassigned | fact | BGW-113 |
| `exit-added` | a call that exits the process added in source | observation | BGW-102 |

Test strength follows the eight-category taxonomy of
[All Smoke, No Alarm](https://arxiv.org/abs/2606.18168) (strong: S1 value, S2 error, containment
or type, S3 both; weak: W1 none, W2 existence, W3 truth, W4 mock calls, W5 snapshot).

A refactor can delete tests honestly, so facts alone exit 0. A fact beside a commit message that
**claims success** exits 1: a subject line starting "Fix", "Resolves", "Implemented" and the like,
or a message saying the tests pass. `--strict` exits 1 on any fact, for CI; observations never
change the exit code. Not checked yet: a test's expected value copied into the source, and files
other than Python and pytest configuration; a report always says so.

Reading history is safe in a hostile repository: only read-only git plumbing runs, with the
programs a repository can name switched off, and the working tree is read directly, never
diffed by git.

**On a pull request.** `--sarif FILE` also writes the facts as
[SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html), which GitHub code
scanning shows as annotations on the lines they are about: a fact as a warning, an observation as
a note. Each result is fingerprinted by its rule, file and subject (never by its message), so a
fact keeps its annotation when its counts change. The GitHub Action in this repository
(`action.yml`) runs `bohrin verify` on every pull request and uploads the SARIF; it needs the
checkout's full history (`fetch-depth: 0`) and `security-events: write`.

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
