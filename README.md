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

> ⚠️ **Pre-release.** The design is in [`docs/`](docs/) and is the thing to read
> and argue with right now. The implementation is in progress; there is nothing
> to install yet.

## What it will do

```console
$ pip install bohrin
$ bohrin audit ./environments/my-taskset

Bohrin  ·  40 tasks  ·  2 probes

  weak-oracle    ████████████░░░  7 tasks accept known-wrong solutions
  determinism    ███░░░░░░░░░░░░  2 tasks score inconsistently

  VERIFICATION GAP: 31 / 100     coverage: 2 of 6 probes
                                 (weak-oracle, determinism)

  9 findings · bohrin-report.json
```

Every finding carries the candidate that passed, why it is wrong, and a command
to reproduce it.

## The two open probes

**Weak oracle** — will the verifier accept work that is provably incorrect?
This is mutation testing with the roles relabelled: your verifier is the test
suite, and a surviving mutant is a wrong solution it accepted.

**Determinism** — does the verifier return the same reward for the same
submission? A grader that disagrees with itself injects noise straight into the
reward signal.

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
