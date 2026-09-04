# bohrin

[![CI](https://github.com/prabhu-gopal/bohrin/actions/workflows/ci.yml/badge.svg)](https://github.com/prabhu-gopal/bohrin/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Everyone tests the AI. Bohrin tests the test.**

When you train a model with reinforcement learning, a program decides whether
each task was solved. That program — the **verifier** — is the only thing the
model learns from. If it is wrong, the model learns the defect, efficiently and
without any visible symptom.

Measured on two widely used code-RL datasets, roughly **one task in four**
accepts a patch that does not fix the bug.

Bohrin finds those tasks in your environments and reports one number.

## What it does

This is a real run against
[`scratchpad`](https://github.com/PrimeIntellect-ai/verifiers/tree/main/environments/scratchpad),
a public environment in the `verifiers` repository — not an illustration:

```console
$ pip install 'bohrin[verifiers]'
$ pip install ./environments/scratchpad      # a taskset is an installed package
$ bohrin audit ./environments/scratchpad --max-tasks 8 --unsafe-local

Bohrin  ·  environments/scratchpad
verifiers_v1 · 8 tasks · 2 probes · isolation: none
  note verifier code ran in-process with no isolation boundary

  determinism    ░░░░░░░░░░░░░░░  no variance observed in 5 runs
  weak_oracle    ███████████████  8 task(s) accept known-wrong solutions

  VERIFICATION GAP: 50 / 100   coverage: 2 of 2 probes

  EXPLOIT ▸ 0: accepted identity_return (reward 1)
           echoes the prompt verbatim instead of answering
           submitted: Call the `scratchpad_roundtrip` tool with word="alpha". It
returns a single word. Then reply wi…
           bohrin audit environments/scratchpad --task 0 --operator
identity_return --unsafe-local
```

Every finding carries the candidate that passed, why it is wrong, and a command
to reproduce it. That last line is copy-pasteable: running it re-runs exactly
that one finding, against that one task, with that one operator.

### What that finding means

`scratchpad` grades with `self.data.word in answer`, and its own prompt contains
`word="alpha"`. So a model that echoes the prompt back scores full marks
**without ever calling the tool** — on all 8 tasks.

That matters more than one weak grader. The environment exists to test
per-rollout isolation, and its docstring offers a mean reward of 1.0 as the
evidence that isolation holds. A mean reward of 1.0 is also what you get from a
model that never touches the server, so the number does not support the
conclusion drawn from it.

Bohrin reports this as an *exploit* rather than a lead because echoing the
question is structurally not an answer — wrongness established without asking
the verifier. Confirmed independently by scoring the same payload through
`verifiers` directly, with Bohrin out of the loop.

### Reading a taskset

Bohrin audits [`verifiers`](https://github.com/PrimeIntellect-ai/verifiers) v1
tasksets. A taskset is an installed Python package, so install it before
auditing the directory it came from.

Scoring invokes the task's reward functions directly — no agent, no model
inference, no rollout — so an audit takes seconds.

A taskset that generates tasks forever is refused unless you bound it with
`--max-tasks N`, rather than run until you notice.

### What it will not do without being asked

Scoring runs the taskset's own code. Bohrin refuses to execute it with no
isolation boundary unless you pass `--unsafe-local`, and the level it ran under
is recorded in the report. A task whose reward function needs a runtime is
refused rather than scored on a partial rubric, because a partial rubric awards
full marks to a submission that does nothing.

## The two open probes

**Weak oracle** — will the verifier accept work that is provably incorrect?
This is mutation testing with the roles relabelled: your verifier is the test
suite, and a surviving mutant is a wrong solution it accepted.

**Determinism** — does the verifier return the same reward for the same
submission? A grader that disagrees with itself injects noise straight into the
reward signal.

### What they will and will not find

The open probes use six deterministic, model-free operators. They cost nothing
but reward invocations and they are reproducible, but they do not find what a
motivated attacker finds.

Across six `verifiers` v1 environments they reported one defect — `scratchpad`,
above — and **no false accusations**. Of the other five: three measured clean at
full coverage, and two Bohrin declined to score, saying so in the report rather
than reporting them clean (`gsm8k` needs a runtime; `reverse_text`'s own
reference answer fails its own verifier).

Two of the three "clean" results are a limit of the operators, not a verdict on
the grader. `glossary` accepts any reply containing the answer as a substring,
and `proposer_solver` grades on the last integer in the reply. Both are
exploitable; no fixed operator here constructs the payload that does it.

That gap is the honest boundary of the open core, and it is stated here rather
than discovered later.

## The rule this codebase is built around

> **Bohrin must never falsely accuse a verifier.**

A missed exploit costs you one finding. A false accusation costs the tool its
reason to exist. So a candidate is only reported as an exploit when its
wrongness is established *independently of the verifier being audited* —
everything else is a lead, not a finding. CI enforces this from both directions,
including a clean fixture where **any** finding fails the build.

## Runs on your infrastructure

Bohrin provisions no compute and transmits no environment data. It runs where
your environments already run, and it refuses to execute generated candidates
unless the required isolation properties are present.

## Documentation

| Document | Contents |
|---|---|
| [docs/01_ARCHITECTURE.md](docs/01_ARCHITECTURE.md) | Layout, core types, plugin seam, concurrency, isolation |
| [docs/02_VERIFICATION_GAP.md](docs/02_VERIFICATION_GAP.md) | What the number means and how it is computed |
| [docs/03_PROBES.md](docs/03_PROBES.md) | Probe designs, including what we refuse to do |
| [docs/04_RELEASE.md](docs/04_RELEASE.md) | What is open, what is not, and why |

## What Bohrin is not

- It does not train models and does not provide a reward signal.
- It does not host or execute environments.
- It does not grade model outputs — that is a verifier's job. Bohrin grades the
  verifier.

## Authorisation

Bohrin generates working exploits against verifiers. Audit only environments you
own or are authorised to assess — the same norm the security industry applies to
offensive tooling.

## Not a novelty claim

The techniques are published. Weak oracle is mutation testing; the adversarial
hacker/fixer loop is [arXiv:2606.08960](https://arxiv.org/abs/2606.08960); the
acceptance rates are [arXiv:2606.16062](https://arxiv.org/abs/2606.16062). What
Bohrin contributes is the productised system and its position — not the
algorithms.

## License

[Apache-2.0](LICENSE). Copyright 2026 Bohrin.
