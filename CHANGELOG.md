# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The **report schema** is versioned separately from the package — see `schema_version` in
any `--json` output. It changes only when the serialized report shape changes.

For the narrative, user-facing version of each release — with upgrade impact and context —
see [`docs/releases/`](docs/releases/), which is what the website's changelog page is built
from. The entries below are the terse canonical record.

## [Unreleased]

### Added

- **A second `verifiers` adapter, for environments built on `load_environment`.** Bohrin
  read only the v1 taskset API, which it detected by the presence of a `taskset.py`. That
  is the API upstream has moved to, but the published ecosystem has not followed: in Prime
  Intellect's environments repository, 111 modules define `load_environment` and **none**
  defines a v1 taskset, so Bohrin recognised **0 of its 109 environments** and answered
  every one of them with "no adapter recognised". The new `verifiers_legacy` adapter reads
  that API. The two never contend for a path — `verifiers_legacy` yields to `verifiers_v1`
  wherever a `taskset.py` is present, so a migrated environment is still read as v1.

  Measured on the environments this unlocks: `allenai_ifeval` scores **50/100**, and the
  finding reproduces outside Bohrin — on its `validate_json_format` task, submitting the
  literal string `0` scores **reward 1.0** while a well-formed English answer scores
  **0.0**, because `0` parses as JSON. A policy trained on that task is rewarded for
  emitting `0` and penalised for answering.

### Fixed

- **A rubric whose reward functions raise is now refused, not scored.** Upstream catches a
  reward function that raises, logs it, and records zero for that function. The total that
  comes back is a partial rubric wearing a complete rubric's number, and it is wrong in
  both directions: nothing can reach full marks, so no exploit is ever reported, and the
  known-good answer fails too, which reads as a verifier that rejects its own ground truth.
  Bohrin now detects this and declines to score the task, naming the cause. On `mastermind`,
  where four of five reward functions need live multi-turn rollout state, the audit
  previously reported `VERIFICATION GAP: 0 / 100` — a clean bill of health for an
  environment it had not measured at all — and now reports `not measured` with
  `coverage: 0 of 3 probes`.

- **Upstream's per-reward-function error logging no longer floods the terminal.** It is
  emitted once per reward function per scored candidate, so one broken rubric turned a
  15-task audit into hundreds of identical stderr lines that buried the report. The
  messages are captured and reported once, as the refusal above.

## [1.1.0] — 2026-09-08

### Added

- **Releases now carry PEP 740 digital attestations.** Publishing moved from `uv publish`
  to `pypa/gh-action-pypi-publish`, which generates and uploads attestations by default
  under Trusted Publishing; `uv publish` does not, and needs a separate action to do it.
  Without them an installer can confirm only that PyPI served a file, not that this
  repository's CI built it from the tag it claims. A tool selling verifiable attestation
  should be able to produce one for its own artifacts. `SECURITY.md` documents how to
  check: `pypi-attestations verify pypi bohrin`.

- **Dependency and static analysis run in CI**, as a separate `Security` workflow:
  `pip-audit` for known vulnerabilities in the dependency tree and `bandit` for static
  analysis, on every push and pull request plus a weekly schedule so a CVE disclosed during
  a quiet week is not discovered at release time. Deliberately **not** one of the required
  checks — a newly published CVE in a transitive dependency would otherwise turn every open
  pull request red for a reason unrelated to the change under review, and `ci.yml`'s job
  names are pinned by branch protection.

- **Dependabot** watches both `pip` dependencies and the GitHub Actions used by the
  workflows. The actions are a supply chain too: a compromised one runs with the release
  job's `id-token: write`, which is the credential that publishes to PyPI.

### Fixed

- **`SECURITY.md` described a different program.** Its scope notes promised that Bohrin
  "never unpickles a checkpoint" and that `--policy` reads safetensors, ONNX and JSON only
  — properties of the robot-dataset analyzer this repository used to hold, none of which
  exist in the verifier auditor. The supported-versions table still listed `0.1.x`, a line
  that is yanked and belongs to `adduct`.

  Worse than being stale, it **omitted the property that actually matters**: auditing a
  taskset runs that taskset's own code, because a verifier cannot be audited without being
  run. The policy now states that plainly, names the three load-bearing guarantees (refusal
  to execute without an isolation boundary, never overstating the boundary that ran, no
  telemetry), and says what is explicitly out of scope — anything `--unsafe-local` enables,
  and escape from `subprocess`, which is documented as blast-radius containment rather than
  a sandbox.

- **The README and design docs still described two probes.** The sample output showed
  `2 probes` and `coverage: 2 of 2`; `docs/03_PROBES.md` opened by saying two ship. Three
  do. The README output is regenerated from a real run.

- **A CI gate no longer fails a clean taskset because a probe did not apply.** The gate
  treated any probe short of full coverage as leaving the verdict undecided, so registering
  a third probe made four clean public environments start exiting `3` — a probe that
  *cannot* apply was being read as an unmeasured gap.

  Those are different things. `ground_truth_rejected` on a taskset with no declared answer,
  or `weak_oracle` when `--operator` selected none, has **nothing to measure** rather than
  something it failed to measure. Only a probe that reports `error` now leaves the gate
  undecided, and the message names which probe and why. Genuinely unmeasurable tasksets
  still exit `3`, and the message is more useful than the coverage fraction it replaced.

- **An empty reply was silently suppressed on any task whose answer is a bare number.**
  Python's compiler discards a bare constant expression statement as dead code, so
  `compile("70")` produces bytecode byte-identical to `compile("")`. The Trivial Compiler
  Equivalence guard added in 1.0.2 therefore judged an empty submission to be "the same
  program as the reference" and dropped it before it ever reached the verifier — along
  with `constant_return`'s literals on the same tasks.

  Numeric answers are the commonest task shape in the ecosystem, so this cost recall
  exactly where it is most expensive, and it cost it **silently**: nothing failed, nothing
  was reported, the candidate simply never ran. It is the mirror image of the false
  accusations that guard was written to prevent, and it was introduced by the fix for them.

  TCE now declines to apply when the reference does not compile to a program that does
  anything — a bare answer is not code, and bytecode comparison has nothing to say about
  it. This cannot reintroduce a false accusation: the candidates it un-suppresses carry
  their own independent grounds. An empty reply is *structurally* wrong whatever the
  reference is, and `constant_return` is guarded by `provably_distinct`, which compares
  payloads as answers rather than as programs. The guard still catches what it was built
  for — emptying a body that was already `pass` remains suppressed.

  No score changes on the public corpus, because the two environments with numeric answers
  (`code_golf`, `gsm8k`) are unmeasurable for unrelated reasons. The defect is real for any
  taskset that grades a numeric answer, which is what most customers audit.

### Added

- **A verifier that crashes on a well-formed submission is now a finding, not noise.** A
  reward function is a program, and one that raises on an ordinary string reply is broken
  in a way its author would want to know about. Bohrin recorded such a failure as an
  `error`, counted it, and reported nothing — closing the top-ranked open weakness in
  `docs/05_ROBUSTNESS.md`. Published reward-hacking work treats exactly this as a
  first-class exploit category (agents avoid unfavourable scoring by "triggering timeouts,
  crashing the harness, exhausting memory or disk") and scores such attempts fail-closed
  **while still logging them as exploit attempts**; Bohrin did the fail-closed half and
  dropped the logging half.

  **The burden of well-formedness is ours**, so the report is guarded twice. Every payload
  Bohrin submits is a plain string, and a disruption is only reported for a task where
  **some other candidate scored successfully** — that isolates the payload as the trigger.
  A task where every attempt failed is a setup, network or environment problem (possibly
  ours), and is reported as an unmeasurable task rather than blamed on the grader.

  A `HarnessDisruption` is **distinct from an acceptance exploit** and carries no ground:
  nothing was accepted. It is deliberately excluded from the `weak_oracle` sub-score, so a
  crash cannot raise the Verification Gap as though the verifier had rewarded wrong work
  — it did the opposite. Measured on the public `verifiers` corpus, no verifier crashes on
  a well-formed payload, so this fires nowhere today; it is reported honestly rather than
  claimed as yield.

- **A reference solution is discovered by contract, not only by field name.** Lookup asked
  whether the answer sat under one of six names we had thought of — a guess about naming
  convention, and it failed on any taskset that named the field after its domain.
  `scratchpad` stores its answer as `word` and grades with `self.data.word in answer`, so
  every one of its tasks was probed with **no reference at all**.

  Bohrin now asks the better question: **which task-data field does the verifier itself
  consult?** That is the contract, and it is readable from the reward function's own source
  — a field the grader compares against is the grader's notion of the right answer, by
  definition. Name-based lookup still runs first, so nothing about existing tasksets
  changes; this is a fallback for the ones that named it otherwise.

  It is **parsed, not pattern-matched**, and that is load-bearing. A regular expression over
  the source matches inside comments, docstrings and string literals: on a reward whose
  docstring mentions a since-renamed field, a regex finds four candidates where the code
  reads one — and because discovery requires *exactly one* candidate, those phantoms
  silently suppress a real reference. The AST sees only what the code does, and also
  recognises `getattr(self.data, "word")`.

  Deliberately conservative, because a wrong reference is worse than none — it becomes the
  baseline, and `constant_return` claims a differential ground against it. Standard
  `TaskData` fields are excluded outright; two candidate fields yield nothing, since there
  is no principled way to choose; non-scalar values are ignored, having no single
  submission form; and an unreadable or unparseable reward yields nothing rather than a
  guess. On the public corpus `scratchpad` gains its reference and no environment gains a
  false finding.

- **A `ground_truth_rejected` probe — the rejection half of the Verification Gap.** Every
  probe so far asked whether a verifier accepts work that is wrong. This asks whether it
  rejects work that is right, by submitting the taskset's **own declared answer**, rendered
  every way the metamorphic-relation catalogue certifies as meaning-preserving, and
  reporting tasks where none was accepted.

  It matters as much as the acceptance side and for the same reason: a verifier that
  rejects correct answers trains a model *away* from correct behaviour, because the
  gradient says the right answer was wrong. Published measurement puts the scale beyond
  argument — across 307,420 verdicts on four widely used verifiers, self-validation (a
  verifier accepting certified-equivalent renderings of its own ground truth) ranges from
  **53.8% to 95.2%**, and separately **over 38%** of model responses in one RL training set
  were false negatives.

  **It deliberately contributes nothing to the Verification Gap.** Its weight is zero, and
  that is a soundness argument rather than caution: three situations produce an identical
  result and Bohrin cannot yet tell them apart. The comparison may genuinely be broken; or
  the verifier may enforce an **output contract the prompt documents** — `reverse_text`
  wants the answer inside `<reversed_text>` tags while storing the bare reversal, so
  refusing it is that verifier working correctly; or the reward may **never read the reply
  at all** — `code_golf` scores `trace.metrics.get("passed")`, set elsewhere in the
  episode, so nothing submitted offline can pass and nothing was truly refused. Both
  confounds were found by running the probe over the public corpus, not predicted. Only the
  first is a defect, and a score pooling all three would report correct verifiers as
  broken.

  Findings are therefore worded as a **search budget**, never a verdict: *"no rendering of
  the declared answer was accepted (8 tried)"* — the same discipline `determinism` follows
  when it quotes detection power instead of claiming determinism. On the public corpus the
  probe is quiet, firing on 2 of 19 environments and staying silent on every clean one, and
  no environment's gap changed.

- **A `false_negation` mutation operator.** Submits an explicit denial of the taskset's own
  declared answer — `The answer is not 70.` for a task declaring the answer is `70`. The
  wrongness is settled by the taskset's ground truth rather than by the reward function
  under audit, so it carries an **invariant** ground.

  It exists because a verifier that decides by asking whether the answer appears
  *somewhere in the reply* cannot tell an assertion from its denial — the denial contains
  the answer too. Substring containment is one of the commonest grader shapes in the
  ecosystem, and no previous operator constructed a payload for it: `empty_body` and
  `refusal` submit nothing recognisable, and `constant_return` submits a literal that a
  substring grader also rejects. This was the measured reason `glossary` scored 0/100 while
  being plainly exploitable.

  **On the public `verifiers` corpus it takes findings from two environments to four.**
  `glossary` and `color_codeword` go from 0/100 to 50/100, and `deepwiki` from 25 to 50.
  Both new findings were confirmed independently, with Bohrin out of the loop: `glossary`
  grades `answer.lower() in reply.lower()`, so a denial scores full marks; `color_codeword`
  extracts the longest standalone A–I run and compares it exactly, so
  `The answer is not ABC.` yields `ABC` and scores full marks. In both cases a reply that
  explicitly states the answer is wrong is rewarded as though it were right.

- **A declared, extensible catalogue of metamorphic relations** (`bohrin.relations`). A
  metamorphic relation states how a verifier's verdict must change — or must not change —
  when its input is transformed in a known way. It is the standard answer to the oracle
  problem, and it is what Bohrin was already doing informally: `reference_renderings` was
  eight hard-coded presentations of one answer, with no stated reason why any of them
  preserved meaning.

  Each relation now carries a **certification** — one sentence saying why the rewriting
  preserves meaning *by construction* — and relations are **partial**: one that does not
  apply to an answer returns nothing rather than guessing. `trailing_zeros_dropped` means
  something for `70.0` and nothing for `banana`, and silence is the correct output. That
  partiality is the soundness mechanism; a relation that over-claims would let Bohrin
  report a verifier for rejecting an answer that was never equivalent.

  Four relations are new and were chosen from measured evidence rather than convenience. A
  category-level audit of four widely-used verifiers over 307,420 verdicts found
  self-validation — a verifier accepting certified-equivalent renderings of its own ground
  truth — ranging from **53.8% to 95.2%**, with **whitespace and punctuation alone
  accounting for 93.0%** of in-contract failures on one verifier, and fractions for a
  further 25.4% on another. So `inline_math`, `decimal_point`, `trailing_zeros_dropped`
  and `latex_fraction` join the existing eight, and presentational rewritings are tried
  first because those are the ones that actually fire.

  A thousands separator (`1000` → `1,000`) is **deliberately absent**: the comma is a
  decimal separator in much of the world, so the rewriting is only meaning-preserving
  under an assumption about locale — and an assumption is exactly what a certification may
  not contain.

  The catalogue is discovered through a new `bohrin.relations` entry-point group, on the
  same footing as probes, adapters and operators. A third party adds a domain's notation
  or a house answer format by publishing a package, not by patching Bohrin. Built-in order
  is fixed in code rather than by the entry-point table, so installing a plugin cannot
  reorder — and therefore cannot change the meaning of — an existing audit's baseline
  search.

  `reference_renderings` keeps its signature and is now a view onto the catalogue, so the
  adapter and every existing caller are unchanged.

### Fixed

- **A task id containing a space broke the reproduction command it printed.** Task ids come
  from the taskset and routinely contain spaces — `glossary` names its tasks after people —
  so `--task Ada Lovelace` split into two arguments and the printed command failed with
  `unrecognized arguments: Lovelace`. For a tool whose claim is that a finding is evidence,
  evidence you cannot re-run is the worst defect available. The 1.0.1 fix quoted the target
  path and a test pinned that; nothing covered the task id, and no environment had exercised
  it until an operator finally produced a finding on one that did. Task ids and operator
  names are now shell-quoted in both probes, and a test parses the printed command back.

- **A taskset with no reward function is no longer reported as clean.** A task carrying no
  reward hook has no verifier: every candidate submitted to it scores zero, so every one is
  "rejected", so `weak_oracle` found no accepted wrong solutions and `determinism` observed
  no variance — and a taskset that was never examined came back as
  **`0 / 100` at `coverage: 2 of 2 probes`**. That is the strongest claim Bohrin can make,
  produced by measuring nothing, and `--fail-on-gap` passed it as a green build.

  Not a hypothetical: **five of the eighteen loadable environments in the public
  `verifiers` repository** — `wordle`, `kuhn_poker`, `openenv_wordle`, `proposer_solver`
  and `wiki_search` — enumerate tasks with zero reward hooks, because they are judged
  cross-agent, at the episode level, or by a seat minted only once a model has run. All
  five reported a clean sweep at full coverage.

  Both probes now refuse such tasks and say why. Those environments report
  `VERIFICATION GAP: not measured  ·  coverage: 0 of 2 probes`, and a CI gate exits 3
  ("gate not evaluated") rather than 0. Findings on environments that do have verifiers are
  unchanged — `scratchpad` 50, `deepwiki` 25.

  This is the same failure as reporting a correct verifier as broken, pointed the other
  way, and it was found by running the tool across a real corpus rather than by reading it.

## [1.0.2] — 2026-09-07

### Added

- **`bohrin audit` can gate a CI job.** Two opt-in flags — `--fail-on-finding` (exit 1 on
  any finding) and `--fail-on-gap SCORE` (exit 1 at or above a Verification Gap) — with a
  documented exit-code contract printed in `--help`: `0` clean, `1` over the gate, `2` bad
  input, `3` gate not evaluated. Previously every completed audit returned 0, so an audit
  reporting 20 exploits at a gap of 50 was indistinguishable from a clean one and the only
  workaround was grepping stdout.

  Gating is opt-in, matching `semgrep scan` and `trivy`, so nothing already scripting
  `bohrin audit` starts failing. **Exit 3 is the part that is not copied from anywhere.**
  Trivy's documented trap is that a pipeline missing its exit-code flag merges happily on
  critical findings; Bohrin has a worse version available, because a gate can pass either
  because nothing was *found* or because nothing was *measured*, and those are different
  claims. A gap of `None`, or coverage short of the full probe set, now exits 3 rather
  than being folded into pass or fail — the same distinction SARIF draws with
  `invocation.executionSuccessful` and error-level `toolExecutionNotifications`. A
  pipeline can then treat "we could not tell" differently from "it is clean". Verified on
  a real environment: `code_golf`, whose tasks all need a runtime, exits 3 rather than
  reporting a false green.

- **`docs/releases/` — one narrative release note per version**, with YAML frontmatter,
  written for people who use Bohrin rather than people reading the source. The website's
  changelog page is built from this folder; `CHANGELOG.md` stays the terse canonical
  record. `docs/releases/README.md` documents the format and the per-PR process, and
  `CONTRIBUTING.md` now asks contributors to update `docs/releases/unreleased.md` alongside
  their changelog entry.

### Changed

- **Findings are grouped by the operator that produced them.** One operator landing on 20
  tasks is one defect with one fix, and the report printed it 20 times — six full blocks
  then "14 more findings", which pushed any *second*, different defect off the screen
  behind the first one's repetitions. `scratchpad` now reports
  `identity_return accepted on 20 tasks` once, with a worked example and the reproduction
  command, and the whole audit fits on one screen. A single-task finding still reads as
  it did. Distinct operators are never merged.

- **A Verification Gap of 0 now says what it does not prove.** Bohrin reports only defects
  its operators can construct a payload for, so a clean result is an under-approximation:
  absence of findings is absence of evidence, not evidence of absence. Two environments in
  this project's own sweep score 0 and are nonetheless exploitable — `glossary` grades by
  substring containment, `proposer_solver` by the last integer in a reply — and no
  model-free operator here builds those payloads. `docs/05_ROBUSTNESS.md` has always said
  so; the report did not, and the report is what people read. A clean score now carries a
  line naming how many operators were tried and what a clean result bounds. A false
  reassurance is a false accusation pointed the other way, and it is the one a
  certification product can least afford.

- **`--no-color` is accepted after the subcommand.** `bohrin audit ./env --no-color` is
  what people type and it failed with `unrecognized arguments`. Both positions now work.

- **`bohrin explain <unknown-probe>` exits 2 rather than 1.** An unknown probe id is bad
  input, and 2 is what every other bad input in the tool returns; leaving it at 1 would
  have collided with the new "findings" code and made the contract incoherent.

- **`pyyaml` is no longer a declared dependency.** It was listed for a `bohrin.yaml`
  config file that was never implemented, so nothing in `src/bohrin/` imported it — which
  breaks this project's own rule that every declared dependency is imported by a line of
  code. A per-project config file can be added later when a user asks for one; the
  dependency comes back with it. `types-PyYAML` is dropped from the dev extra for the same
  reason. No runtime behaviour changes.

### Fixed

- **A taskset that fails to load is a message, not a traceback.** Loading imports the
  customer's own package and runs its module-level code, so it can raise anything — but
  only `ModuleNotFoundError` was handled, and everything else escaped the CLI's user-error
  set as a raw Python stack trace with exit 1. This is not exotic: it was reached on the
  first attempt with a taskset written against a slightly different `verifiers` API
  (`import verifiers as vf` rather than `verifiers.v1`), and `verifiers` is pre-1.0, so
  version drift is the normal case rather than the edge case. A stack trace reads as
  *Bohrin crashed* when the truth is *your taskset did not load* — the blame inversion
  this project exists to avoid. A new `TasksetLoadError` names the taskset, quotes the
  underlying error, states that the fault is not Bohrin's, and exits 2; the original
  exception stays chained so nothing is lost.

- **Bohrin no longer reports a correct verifier as exploited.** Four paths claimed a
  wrongness ground from a difference in *source* rather than a difference in
  *behaviour*: `constant_return` submitting `"1"` against a reference of `"1.0"` (a
  correct numeric grader accepts it) or `"True"` against `"true"` (a correct
  case-folding grader accepts it); `negate_condition` inverting a branch whose two arms
  do the same thing; and `drop_side_effect` emptying a body that was already `pass`,
  producing a mutant byte-identical to the reference. The first mattered most — numeric
  answers are the commonest task shape in the ecosystem, and the result was a
  Verification Gap of **50/100 against a flawless grader**, which is the one failure the
  governing rule forbids outright.

  A new `bohrin.mutate.equivalence` module supplies two soundness checks, both of which
  can only ever *remove* findings. `provably_distinct` refuses a ground unless the two
  payloads differ under every normalisation a correct verifier might apply — whitespace,
  case, numeric parsing, Python literals, JSON, and the common spellings of true and
  false. `code_equivalent` is Trivial Compiler Equivalence on Python bytecode: sources
  that compile to the same program are the same program. `negate_condition` now carries
  **no ground** and can only produce a lead, because TCE cannot rescue it — an inert
  negation compiles differently precisely because the source differs. That is the same
  reasoning that keeps `off_by_one` and `swap_operator` unregistered.

  The clean fixture was an exact-string matcher, which models a *strict* verifier and
  therefore could not express this class of failure at all. `tests/_fixtures.py` now
  carries `LENIENT_CORRECT`: graders that are generous about presentation and still
  entirely right. Every registered operator runs against every one of them, and a
  counterweight test asserts a genuinely weak verifier is still caught with a ground
  attached, so the guards cannot pass by silencing the probe. Findings on real
  environments are unchanged — `scratchpad` still reports 50/100 with eight exploits.

- **Documentation now matches the code.** `execute/runner.py` claimed a Python 3.10 floor
  (the floor is 3.11) and attributed the `gather`-over-`TaskGroup` choice to that; the real
  reason — `TaskGroup` cancels every sibling when one task raises, which would abandon an
  audit over a single hung verifier — is now in the docstring. `docs/01_ARCHITECTURE.md`
  referenced `report/html.py` and `report/json_out.py` (neither exists) and showed core
  types that had drifted from `ir/task.py`. `docs/03_PROBES.md` listed seven mutation
  operators including two (`off_by_one`, `swap_operator`) that are deliberately unregistered
  pending the differential comparator, and omitted `refusal`, which ships. `CONTRIBUTING.md`
  named Python 3.10 as supported. None of these changed behaviour; all of them would have
  been found by a reader comparing a doc against the source.

## [1.0.1] — 2026-09-05

A correctness and first-run release. Every item below was found by running 1.0.0 against
real public `verifiers` environments, not by the test suite — which is itself the finding
worth recording.

### Fixed

- **`--max-tasks` now actually bounds an audit, and an infinite taskset is refused rather
  than hung.** The adapter read tasks by calling `Taskset.load()`, which is the subclass
  hook that *builds* tasks; upstream applies `head`/`shuffle` views and the config-layer
  system prompt on the iteration path instead. Calling `load()` discarded both. The visible
  cost was severe: auditing `color_codeword` — an `INFINITE` taskset in the `verifiers`
  repo — ran past ten minutes with no output and growing memory, because the probes
  materialise the task list before scoring. The same run now completes in 10.5 seconds at
  full coverage. The quieter cost was worse: a taskset configured with a system prompt was
  audited without it, which is not the task the customer runs. As a backstop, a taskset
  still marked infinite after any `--max-tasks` bound is now refused with a message naming
  the flag, because hanging with no output is the worst way for an audit to fail.
- **The reproduction command printed on every finding now runs.** It named `--task` and
  `--operator`, neither of which existed, and omitted the taskset path — so the first
  thing a reader would do with a finding was paste a command that exits with
  `unrecognized arguments`. For a tool whose entire claim is that a finding is evidence,
  evidence you cannot re-run is the worst possible defect. Both flags are now implemented
  and honoured by both probes, the target is included and shell-quoted, and
  `--unsafe-local` is appended only when the audit actually ran without a boundary. A test
  now feeds the printed command back through the argument parser, so this cannot rot again.
- **A missing extra is reported before the isolation refusal.** Auditing a `verifiers`
  taskset without `bohrin[verifiers]` installed answered with "refusing to execute verifier
  code with no isolation — start docker", so the user fixed Docker, re-ran, and only then
  learned they needed the extra. Without the extra the audit cannot run at *any* isolation
  level. The check is a new `Adapter.check_requirements` hook that runs before the gate and
  deliberately imports nothing from the taskset — the isolation boundary is unchanged.
- **Counts read as English.** `1 tasks`, `1 of 1 probes` and `1 task accept` all appeared
  in a single-task audit — and a report selling rigour cannot misspell its own summary
  line. Nouns and verbs now agree with the count everywhere in the terminal report.
- **Long payloads are elided with `…` instead of cut mid-word.** A payload truncated at
  exactly 96 characters read as a rendering bug rather than an abbreviation, and the
  payload is the evidence a reader judges the finding by.
- **A path that does not exist now says so.** Every adapter's `detect` returns 0.0 for a
  missing path, so a mistyped path was indistinguishable from a real directory in an
  unsupported format and was answered with advice about installing extras — sending the
  user to fix a problem they did not have.

### Known limitations

- **Recall on real environments is bounded by the six open operators, and that is visible
  in the numbers.** Auditing six `verifiers` v1 environments found one real defect:
  `scratchpad` scores with `self.data.word in answer` while its own prompt contains
  `word="alpha"`, so echoing the prompt back scores full marks without ever calling the
  tool — 8 of 8 tasks, gap 50/100, confirmed independently through `verifiers` with Bohrin
  out of the loop. The environment's docstring cites a mean reward of 1.0 as evidence that
  per-rollout isolation works; that evidence does not hold, since 1.0 is reachable without
  touching the server. Of the other five, three measured clean at full coverage and two
  were declined rather than reported clean (`gsm8k` needs a runtime; `reverse_text`'s
  reference fails its own verifier). Two of those three "clean" results are a limit of the
  operators rather than a verdict on the grader: `glossary` grades by substring containment
  and `proposer_solver` by the last integer in the reply, both exploitable, but no
  model-free operator here constructs the payload that does it. No false accusation was
  made in any run.

## [1.0.0] — 2026-09-02

The first release of Bohrin as a verifier auditor.

**On the version number.** The 0.x line on PyPI belonged to a different tool — static
analysis for robot demonstration data — which was renamed and is published as
[`adduct`](https://pypi.org/project/adduct/), with its full history in that repository.
Those releases are yanked and point users there. The major bump is deliberate: this is a
different program, not an upgrade.

**What it measures.** Two probes, and the honest limits of each are reported rather than
implied. `weak_oracle` submits provably-wrong candidates and records the ones a verifier
accepts; a candidate is only reported as an exploit when its wrongness was established
independently of the verifier being audited, and where a reference exists it must pass
first. `determinism` submits one identical candidate repeatedly and reports disagreement,
quoting the detection power of the run because a null result bounds the flake rate rather
than proving determinism.

**Known limits, stated deliberately.** A task whose reward function requires a runtime is
refused rather than scored on a partial rubric. `docs/05_ROBUSTNESS.md` records seven known
weaknesses with the evidence behind each — most importantly that harness disruption is not
yet reported as a finding, and that the false-positive rate is unmeasured until a public
sweep measures one. No accuracy claim is made in the meantime.

### Added

- Design documentation for the open core in `docs/`: architecture, the Verification Gap
  specification, the two open probe designs, and the open/proprietary boundary.
- **Isolation is classified, enforced and recorded.** Scoring runs the taskset's own
  reward functions, which is arbitrary third-party code. Bohrin now refuses to execute it
  with no boundary unless `--unsafe-local` is passed, and the level used is written into
  the report — a result produced in-process must never be mistaken for one produced inside
  a container. The level below a container is called `subprocess` and described as
  blast-radius containment, never a sandbox: process limits prevent denial of service, not
  escape.
- **Concurrency adapts to the machine.** Derived from core count and free memory rather
  than fixed, so an audit does not crowd out the laptop running it. macOS is handled
  explicitly because it exposes no `SC_AVPHYS_PAGES`, which would otherwise leave the
  memory guard permanently disabled on exactly the machines it protects.
- **The `verifiers` v1 adapter.** Bohrin can now audit a real taskset. Candidates are
  scored by constructing a trace and invoking the task's reward functions directly — no
  agent, no model inference, no rollout — so a first audit takes seconds.
- The probe framework, the `weak_oracle` and `determinism` probes, the baseline mutation
  operators, the Verification Gap with its mandatory coverage descriptor, and the
  `audit` / `list-probes` / `explain` command surface.

- **`weak_oracle` now requires a green baseline.** Where a task ships a reference
  solution it is submitted unchanged first and must pass. Mutation testing assumes the
  unmutated code passes; without that, an accepted mutant cannot be distinguished from
  Bohrin submitting in a form the verifier does not understand — and reporting the former
  when the latter is true blames a customer for our own bug. Tasks that fail their
  baseline are excluded from the score and reported; if none can be baselined the probe
  reports `error` rather than `ok`.
- **`determinism` now reports the statistical power of its own measurement.** A null
  result bounds the flake rate rather than establishing determinism: at five repeats a
  verifier that flips 5% of the time is missed roughly 77% of the time. The terminal
  headline reads "no variance observed in 5 runs" instead of implying a conclusion.

### Changed

- **Python 3.11 is the supported floor**, down from 3.10 in the previous project. Two
  independent reasons: `verifiers`, the only adapter target at launch, requires
  `>=3.11,<3.14`; and Python 3.10 reaches end of life on 31 October 2026. The CI matrix
  and branch protection were updated to match — required checks went from nine to seven,
  and leaving the 3.10 names in place would have blocked every future merge.

### Changed

- **This project is now a verifier auditor, not a dataset analyzer.** The previous tool —
  static analysis for robot demonstration data — was renamed and is published as
  [`adduct`](https://pypi.org/project/adduct/), with its full history in that repository.
  The `bohrin` name now belongs to this project. Releases 0.1.0 and 0.2.0 on PyPI are
  yanked and point users at `adduct`; the verifier auditor starts at 1.0.0, so that the
  discontinuity reads as a break rather than an upgrade.

[Unreleased]: https://github.com/prabhu-gopal/bohrin/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/prabhu-gopal/bohrin/compare/v1.0.2...v1.1.0
[1.0.2]: https://github.com/prabhu-gopal/bohrin/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/prabhu-gopal/bohrin/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/prabhu-gopal/bohrin/releases/tag/v1.0.0
