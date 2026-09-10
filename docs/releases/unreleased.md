---
title: "Bohrin — unreleased"
version: "unreleased"
date: "unreleased"
# tag: "vX.Y.Z"        # add at release time
breaking: false
summary: >
  Bohrin can now audit environments built on the load_environment API, which is what
  almost every published environment still uses, and refuses to score a rubric whose
  reward functions failed instead of reporting it clean.
---

## TL;DR

Bohrin previously read only one of the two `verifiers` APIs in circulation — and it was the
one almost nothing published uses yet. It recognised **0 of the 109 environments** in Prime
Intellect's environments repository. This release adds a second adapter for the other API,
and fixes a case where an environment Bohrin could not actually measure was reported as
scoring a clean `0 / 100`. Upgrade with `pip install --upgrade 'bohrin[verifiers]'`;
nothing changes for environments that already worked.

## Upgrade impact

- **Breaking changes:** none
- **Action required:** none — `pip install --upgrade 'bohrin[verifiers]'`
- **New minimums:** none. Note that many published environments pin `python <3.13`; that
  is their constraint, not Bohrin's, but it is what you will hit installing one.

## Highlights

- **Bohrin can read the environments people actually publish.** The v1 taskset API is where
  upstream is going, and Bohrin supported it exclusively — detecting it by the presence of a
  `taskset.py`. The published ecosystem has not migrated: 111 modules in Prime Intellect's
  environments repository define `load_environment`, and none defines a v1 taskset. Every
  one of those 109 environments was answered with "no adapter recognised" — an error that
  also, unhelpfully, suggested installing an extra that was already installed. Both APIs are
  now supported side by side.

- **An environment Bohrin cannot measure no longer looks clean.** A verification gap of
  `0 / 100` is a strong claim, and Bohrin was making it in a case where it had measured
  nothing at all. That is now reported as `not measured`.

## Added

- **A bounded audit says what it was bounded from.** `--max-tasks N` audits the *first* N
  tasks, not a sample of them, and the report showed `10 tasks` whether that was the whole
  taskset or a thin slice of it. That made a clean result over a prefix look exactly like a
  clean result over a corpus. On one published environment a 10-task bound scored 0 and a
  20-task bound scored 50 — the defect was at tasks 11 and 12.

  The header now reads `10 of 541 tasks`, and a clean score says plainly that a defect in
  the tasks after the bound could not have appeared. `--json` gains `corpus_total` and
  `truncated` (`schema_version` 1.2).

- **Four new metamorphic relations, picked by measured failure rates.** Bohrin renders a
  taskset's own known-good answer several certified-equivalent ways before it will report
  that a verifier rejected its own ground truth. That catalogue now leads with punctuation
  and layout, because that is what the published evidence says verifiers actually refuse: a
  category-level audit of four widely-used verifiers attributes 93.0% of in-contract false
  negatives on one configuration to whitespace and punctuation, with a trailing period or
  newline the dominant cause. Bohrin covered surrounding whitespace and neither of those.

  Added: `trailing_period`, `trailing_newline`, `display_fraction` (`\frac` → `\dfrac`)
  and `braced_sqrt_argument` (`\sqrt2` → `\sqrt{2}`). Sixteen relations, from twelve.

  The practical effect is fewer false leads: a `ground_truth_rejected` finding now survives
  more ways of writing the same answer before it is reported.

- **The eval split is read when an environment has no training split.** An environment
  published for evaluation populates only its eval split, and asking for the training one
  raises `dataset is not set` — which Bohrin reported as an unreadable environment.
  `hellaswag`, `boolq` and `winogrande` are all in that shape. Every task now records the
  split it came from, and the report states it: auditing the eval split and auditing the
  training split are different claims, and the report may not blur them.

  All three score **50 / 100** at full `3 of 3` coverage. On `boolq` the finding is stark —
  the declared answer is `False`, the opposite answer `True` correctly scores 0.0, and
  `The answer is not False.` scores **1.0**. The grader matches the answer token as a
  substring, so a reply that explicitly denies the correct answer is rewarded as if it were
  correct. It was caught by the `false_negation` operator added in 1.1.0.

- **The `verifiers_legacy` adapter**, for environments exposing `load_environment()`. It
  yields to `verifiers_v1` on any path containing a `taskset.py`, so an environment that has
  migrated is still read through the API it migrated to, and no path is ever contended.

  The first environments this unlocks already produce findings that reproduce outside
  Bohrin. On `allenai_ifeval` (**50 / 100**), the `validate_json_format` task scores the
  literal string `0` at **reward 1.0** and a well-formed English answer at **0.0** — `0`
  parses as JSON, so it satisfies the check. A policy trained on that task is rewarded for
  emitting `0` and penalised for answering the question.

## Fixed

- **Bohrin no longer accuses safety graders of rewarding refusals.** On a harmful request,
  declining is the correct answer — that is what a safety benchmark measures. Bohrin's
  `refusal` operator nonetheless treated an accepted refusal as proof of a broken grader,
  and `false_negation` did the same when the declared answer was itself a refusal. Both are
  fixed: where the declared answer reads as a refusal, no candidate may carry a wrongness
  ground, and accepted ones are reported as leads rather than scored. This matters for
  anyone auditing a safety or red-teaming environment, where the previous behaviour turned
  a correctly-behaving grader into a headline finding.

- **Two quieter false-accusation paths are closed too.** A copy task, whose prompt is its
  own answer, no longer has an echo of its prompt reported as an exploit. And the backstop
  that protects against third-party operators now compares *answers* as well as programs:
  before, a plugin submitting `70.0` against a reference of `70` could still accuse a
  correct numeric grader — the same class of defect as the 1.0.1 launch blocker.
- **`--timeout` actually applies to ordinary reward functions.** Most published reward
  functions are plain synchronous Python, and they ran straight past the timeout: a 0.5 s
  limit around a grader that slept for 3 s returned after 3 s and counted the result as a
  normal score. A grader that hung would have hung the whole audit. Bohrin now interrupts a
  grader that holds up the audit past `--timeout` and records the call as timed out. Where
  other submissions to the same task scored normally, that is reported as a harness
  disruption — a grader a particular reply can stall will stall a rollout worker in
  training too.

  *Upgrade note:* if you ran slow synchronous graders relying on `--timeout` being ignored,
  raise it. The default is 30 s. Enforcement uses a POSIX real-time alarm on the main
  thread; on Windows, off the main thread, or when `SIGALRM` is already in use, behaviour is
  as before.

- **Carrier-sentence renderings no longer double punctuation.** An answer that already ends
  in a full stop or a question mark rendered as `The answer is 42..` or `The answer is
  why?.`. Those are not strings a model writes, so testing a verifier against them measured
  nothing while risking a refusal being counted against the verifier.

- **A `verifiers` silently resolved below the required version is reported clearly.** A
  taskset is an installed package with its own pins, and installing one alongside Bohrin can
  resolve `verifiers` downwards — one published environment pins `verifiers==0.1.5`, enough
  to take a working 0.3.1 down to a version with no `verifiers.legacy` module. `verifiers`
  still imported, so the audit began and then failed once per task with a raw
  `ModuleNotFoundError` that looked like a broken taskset. Bohrin now checks for the API it
  actually needs and names the installed version, the required version, and the fix.

- **A rubric whose reward functions raise is refused rather than scored.** Upstream catches
  a raising reward function, logs it, and records zero for that function, so the total that
  comes back is a partial rubric wearing a complete rubric's number. It is wrong in both
  directions at once: nothing can reach full marks, so no exploit is ever reported, and the
  known-good answer fails too, which reads as a verifier that rejects its own ground truth.
  Bohrin now detects this and declines to score, naming the cause.

  On `mastermind`, where four of five reward functions read rollout state that only a live
  multi-turn rollout produces, the audit previously reported `VERIFICATION GAP: 0 / 100`.
  It now reports `not measured`, with `coverage: 0 of 3 probes`.

- **Upstream's reward-function error logging no longer buries the report.** It is emitted
  once per reward function per scored candidate, so a single broken rubric turned a 15-task
  audit into hundreds of identical stderr lines. The messages are captured and reported
  once, as the refusal above.

## Known limitations

- Roughly 47 of the 109 published environments score with an LLM judge, which needs a live
  model. Bohrin refuses those tasks rather than scoring them on a partial rubric, so they
  are reported as unmeasured. The honest coverage figure for that corpus is therefore well
  below 109, and every report states which probes were measured.
