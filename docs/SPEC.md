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
| `bohrin/constant-implementation@1` | `constant_implementation` | the reference with every function returning a constant of its return type (`0`, `""`, `[]`, `{}`, `False`, …) | BGW-101 | Structural, or a lead (below) | `hollow_program` |
| `bohrin/raise-not-implemented@1` | `raise_not_implemented` | the reference with every function body replaced by `raise NotImplementedError` | BGW-101 | Structural | `hollow_program` |

All three need a reference in which some function does work: one whose functions are only
docstrings, `pass`, `...` or `raise NotImplementedError` (an interface) gets no submission.

- **The constant's type** comes from the function's return annotation, or else from what the
  reference returns: a literal, a comprehension, a comparison, a built-in call with a fixed type
  (`len`, `sorted`, `str`, …), or a local name's first assigned value. Where neither fixes one
  type the constant is `None`; if every constant would be `None` nothing is submitted, because
  that is the empty implementation again. Special methods keep their bodies.
- **A constant is only a lead** when no function of the reference both reads its inputs (its
  parameters, `self` or `cls`) and returns a value the syntax does not fix: such a reference may
  itself return the constant.
- **Raising is not submitted** when the reference's only work is raising an error: one error
  raised in place of another is not provably wrong.

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

**Correct-work acceptance** — of the correct rewritings of a task's reference (the positive
controls above), what share did the grader accept? 0–100, higher is better.

- Counted per task and relation. A rewriting tried more than once counts as accepted only if it
  was accepted **every** time.
- The baseline (the reference unchanged) is a gate, not a point: it is never counted, and
  acceptance on a task is measured only when its baseline was run and accepted.
- Printed with its sample, a 95% Wilson interval and the number of relations measured. Nothing
  measured is `not measured`, never 100.

**The two are printed side by side and never merged.** A grader that rejects everything scores
100 on the Coverage Score; correct-work acceptance exposes it. Any single number made from the two
could be raised by trading one for the other.

**Which tasks are scored.** Each exclusion is listed with its task and reason, never dropped
silently:

| Rule | Left out | Why |
|---|---|---|
| The grader rejected the task's reference, on any run | the task, from both numbers | a grader that fails the reference is not measuring the task, and rejecting a cheat there is not catching it |
| The grader paid past full marks on any submission to the task | the task, from both numbers | full marks are then not known, so neither accepted nor rejected can be read |
| An attempt could not run | that attempt, from both sides of every rate | a crash counted as rejected would score as a catch |

**Per shape, then overall.** Tasks are scored per grader shape, then all together. Each shape
names the weakness classes that apply to it (active classes of a scoring category that list the
shape) and that nothing in the run measured. A class is measured when a probe whose manifest names
it produced a counted result.

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
a test moved to another file, or into, out of or between classes, never looks like a deleted one.

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
or type, S3 both; weak: W1 none, W2 existence, W3 truth, W4 mock calls, W5 snapshot). A check
joined with `and` has the kinds of all its parts; one joined with `or` passes when any part holds,
so it is only as strong as its weakest part. A comparison with `None` (`is`, `==` or `!=`) is an
existence check, a comparison of a mock's call record (`call_count`, `called`) is a mock-call
check, and `assertTrue(x == 5)` is read by its argument.

A tolerance counts whether it is given by keyword or by position (`pytest.approx(x, 0.5)`), and
NumPy's `isclose` is kept apart from the standard library's, whose arguments and defaults differ.
A check is swallowed inside a `try` (or `try`/`except*`) whose handler catches `AssertionError`,
`Exception` or everything, and inside `with suppress(...)` of one of those.

A refactor can delete tests honestly, so facts alone exit 0. A fact beside a commit message that
**claims success** exits 1: a subject line starting "Fix", "Resolves", "Implemented" and the like,
or a message saying the tests pass. `--strict` exits 1 on any fact, for CI; observations never
change the exit code. Not checked yet: a test's expected value copied into the source, and files
other than Python and pytest configuration; a report always says so.

Reading history is safe in a hostile repository: only read-only git plumbing runs, with the
programs a repository can name switched off, and the working tree is read directly, never
diffed by git. A file over 2 MB is not read, and a committed one is refused from its size in the
tree listing, before its content is loaded. Symlinks, and files reached through a symlinked
directory outside the repository, are not read. A pytest configuration file that does not parse
is listed as not checked rather than compared: pytest stops on it instead of running fewer tests.

**On a pull request.** `--sarif FILE` also writes the facts as
[SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html), which GitHub code
scanning shows as annotations on the lines they are about: a fact as a warning, an observation as
a note. Each result is fingerprinted by its rule, file and subject (never by its message), so a
fact keeps its annotation when its counts change. The GitHub Action in this repository
(`action.yml`) runs `bohrin verify` on every pull request and uploads the SARIF; it needs the
checkout's full history (`fetch-depth: 0`) and `security-events: write`.

## Conformance

A conformance suite proves that a **grader-checking tool is sound**: it flags every grader with a
defect and never flags a correct one. It follows test262 and the JSON Schema Test Suite (open
cases as data, any runner) and the paired good and bad cases of NIST's Juliet suite.

**Fixtures.** Each weakness of a level has a pair of graders in `conformance/<level>/`: one
correct, one with exactly that defect. They are self-contained Python files, written for the
suite, with the interface in `conformance/README.md`. Their expected results are in
`src/bohrin/conformance/bcl-1.toml`. The tests hold each pair to what it claims:
- every correct grader accepts the reference and every certified rewriting of it;
- each grader with a defect shows it on a demonstration its correct partner gets right;
- otherwise, it agrees with its partner.

| Level | Shapes | Weaknesses | In the suite now |
|---|---|---|---|
| BCL-1 | program, io | 101–105, 120, 123, 124, 126, 127 | 101, 104, 120, 123, 124, 126, 127 (version 1) |
| BCL-2 | workspace | BCL-1 and 108, 109, 112, 117 | not yet |
| BCL-3 | container | BCL-2 and 110, 111, 113, 116, 138 | not yet |
| BCL-4 | container, hardened | BCL-3 and 130–132, verified structurally | not yet |

**Results.** A tool reports each fixture in the `https://bohrin.com/schema/conformance-results/v1`
format: `ran` with the weakness classes it flagged, `error` or `skipped`. `bohrin conformance
check FILE` (listed by `bohrin help more`) runs no grader; it compares the results with the
expected ones. A tool **achieves the level** when, for every weakness with fixtures:
- it flags the grader with the defect with that weakness (detected);
- it flags nothing on the correct grader (clean);
- it flags no other weakness on the grader with the defect (no misattribution).

A fixture that errored, was skipped or is missing is neither detected nor clean. One false
accusation fails the level however much was found. Beside the level, the check prints the
true-positive rate over graders with a defect, the false-positive rate over correct graders, and
their difference (Youden's index, the OWASP Benchmark's score) as a score from −100 to 100.
Weaknesses of the level with no fixtures yet are named, and the level is claimed only over the
others. Exit codes: 0 achieved, 1 not achieved, 2 the file cannot be checked (another level or
version, an unknown or repeated fixture, or a record the schema refuses).

## Registry records

A registry record is the public, citable form of a defect in a coding grader or its harness, as a
CVE record is of a software vulnerability. It is published as the JSON Schema
`https://bohrin.com/schema/registry-record/v1` (`src/bohrin/registry/record.v1.json`) and read by
`bohrin.registry.read_record`. The records themselves are one JSON file each, published under
CC-BY-4.0 as a git repository.

- **OSV field names where they fit:** `schema_version`, `id` (`BVR-<year>-<number>`), `aliases`,
  `related`, `modified`, `published`, `withdrawn`, `summary` (one line, at most 120 characters),
  `details`, `affected` (with OSV `ranges` of type `GIT`, `SEMVER` or `ECOSYSTEM`, and events
  `introduced`, `fixed`, `last_affected` or `limit`, one per event), `references` and `credits`
  with OSV's types.
- **What a stranger needs to check it:** `weakness` (one or more `BGW-` classes), `probe`,
  `findings` (the `BF-` records it rests on), `submission` (a digest, never the submission
  itself, defined exactly as in the finding record), `score_received`, `ground`, `reproduce`.
- **Its standing:** `status` (`reported`, `confirmed`, `fixed`, `disputed`, `withdrawn`; a
  withdrawn record says when), `numbering_authority`, and `disclosure`.
- **An artefact, never a person:** `affected[].artifact` is an environment, benchmark, grader or
  harness.

Three rules no JSON Schema can express are checked by the reader: every date is a real calendar
date; every weakness is a class of the weakness list; and the notification policy
([disclosure.md](disclosure.md)): `published` is never before `disclosure.maintainer_notified`,
and is at least 45 days after it unless `status` is `fixed` and the maintainer agreed to earlier
publication. The example [examples/BVR-0000-00000.json](examples/BVR-0000-00000.json) describes the
example grader in this repository; year `0000` marks an example.

## The decisions file

A repository records what it decided about findings in `.bohrin/decisions.toml`, committed so
the whole team shares it (`bohrin.decisions`). The format is open, so any tool can read and write
it.

```toml
version = 1

[[decision]]
finding = "BF-7K3Q9D2M1X"
action = "ignore"
reason = "the task's deliverable is the file's existence"
decided = 2026-10-01
expires = 2027-01-01
```

- **`action`**: `ignore` stops showing the finding and counts it in its probe's dismissal rate,
  saying nothing about whether it is right; `dispute` says the finding is wrong, keeps it visible
  as disputed, and counts it neither way in the error rate until the dispute is resolved.
- **`reason`** is required and kept, because reasons are how a broken check is found.
- **`decided`** and the optional **`expires`** are TOML dates, unquoted. On its expiry date a
  decision stops holding and the finding shows again. A date that cannot be read is an error,
  never read as "no expiry", and an expiry must be after the decision.
- One decision per finding. No field names a person: the repository's history records who.
- A tool writes the file sorted by finding ID, so a change reads as a small diff, and escapes any
  reason so it reads back exactly and cannot add a decision of its own.
- Each decision maps onto a SARIF suppression: `kind` external, `status` accepted for an ignore
  and underReview for a dispute, the reason as its `justification`.

## Error rates

A tool that accuses graders publishes how often it is wrong, and how much it misses, by a method
anyone can apply to any tool (`bohrin.stats.error_rate`). It reads what a tool reported and what
became of it; it runs nothing.

**Precision: false accusations per 1,000 proven findings.** One line per reported finding in the
`https://bohrin.com/schema/finding-outcome/v1` format: its `finding` ID, `probe`, `battery`,
`level`, `outcome` and whether a user `dismissed` it.

| Outcome | Counted |
|---|---|
| `stands` | resolved, correct |
| `withdrawn-after-dispute` | resolved, a false accusation |
| `contradicted-by-fixture` | resolved, a false accusation: a correct conformance fixture was flagged |
| `disputed` | neither way until resolved; reported |

- Per battery, overall and per probe, with a Wilson 95% interval. No false accusation in 40
  findings reads "0 per 1,000 (95% CI 0–88)", never "never wrong".
- Only `proven` findings enter the headline; `proven-experimental` ones are reported apart.
- The **dismissal rate** per probe (findings a user dismissed without disputing, of those
  reported) is printed beside it. It is not an error, but a signal: Google counts a result
  developers do not act on as an "effective false positive".

**Recall on planted weaknesses.** One line per known, planted weakness in a corpus, in the
`https://bohrin.com/schema/recall-row/v1` format, with three stages modelled on Magma's reached,
triggered and detected ([Hazimeh, Herrera and Payer, 2020](https://arxiv.org/abs/2009.01120)):
**tried** (a probe for the weakness was submitted), **accepted** (the grader paid, so the defect was
exercised) and **proven** (a finding with a reproduction). Each implies the one before, and each is
reported per weakness class as a share of the planted instances, with its interval.

**Errata.** A mistake found in a released part of the standard (the weakness list, the battery,
the conformance fixtures, a published format) is recorded in [ERRATA.md](../ERRATA.md) with what it
affects and what a result produced with it means now, the way LiveCodeBench keeps a public errata
list for its benchmark.

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
