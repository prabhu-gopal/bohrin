# bohrin

[![CI](https://github.com/prabhu-gopal/bohrin/actions/workflows/ci.yml/badge.svg)](https://github.com/prabhu-gopal/bohrin/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Everyone tests the AI. Bohrin tests the test.**

When you train a model with reinforcement learning, a program decides whether each task was
solved. That program — the **verifier**, or grader — is the only thing the model learns from.
If it is wrong, the model learns the defect, efficiently and without any visible symptom.

This repository is the open standard for checking a grader: what to try against it, when a
submission it accepts is provably wrong, and how to score what was found. Every definition is
public, so anyone can read exactly what was tried and recompute the result.

## What is in it

| Part | What it defines |
|---|---|
| **The battery** — `bohrin.mutate` | Nine fixed, model-free operators that construct known-wrong submissions for a task: an empty reply, the prompt echoed back, a refusal, a constant, an explicit denial of the answer, several answers at once, a degenerate reply, and two code-level mutations of a reference solution |
| **The wrongness rules** — `bohrin.mutate.battery`, `bohrin.mutate.equivalence` | When a candidate may be called wrong: only when that is established independently of the grader, and never when it is the declared answer written another way |
| **The answer rewritings** — `bohrin.relations` | Seventeen certified meaning-preserving renderings of a correct answer (`70` → `\boxed{70}`, `70.0`, `The answer is 70.`), each carrying the one-sentence argument for why it preserves meaning |
| **The scoring rules** — `bohrin.scoring` | The Coverage Score, the Verification Gap with its coverage descriptor and two sides, and a Wilson interval on every rate |
| **The record types** — `bohrin.ir` | Tasks, candidates, verdicts, the grounds a candidate may claim, and the finding records |

## Using it

```console
$ pip install bohrin
```

```python
from bohrin.ir.task import Task
from bohrin.mutate.battery import battery

task = Task(id="0", prompt="What is 7 x 10?", reference="70", reward_fns=("my_grader",))

for candidate in battery(task).grounded:
    # Every grounded candidate is provably wrong for this task. A grader that pays full
    # marks for one of them is rewarding wrong work.
    print(candidate.provenance.operator, repr(candidate.payload[:40]), candidate.ground)
```

`battery(task).leads` holds the candidates that were tried but cannot be shown to be wrong —
on a safety task a refusal may be the correct reply, for example. A grader accepting one is
worth a human's attention, and is never counted as a defect.

### The Coverage Score

Offer every candidate to your grader and record whether it paid full marks. The Coverage Score
says what fraction of the ways a task can be passed without doing it the grader caught:

```python
from bohrin.ir.task import Task
from bohrin.mutate.battery import battery
from bohrin.scoring.coverage import Attempt, coverage_score

tasks = [
    Task(id="0", prompt="What is 7 x 10?", reference="70", reward_fns=("contains",)),
    Task(id="1", prompt="What is 6 x 7?", reference="42", reward_fns=("contains",)),
]


def my_grader(task, reply):
    return task.reference in reply  # a common, weak shape: the answer appears somewhere


attempts = [
    Attempt(task.id, candidate, accepted=my_grader(task, candidate.payload))
    for task in tasks
    for candidate in battery(task).candidates
]
print(coverage_score(attempts))
```

```console
COVERAGE SCORE: 60 / 100   95% CI 31–83   6 of 10 caught   categories: 5 of 5 (battery 1)
```

That grader catches empty replies, malformed replies and wrong answers, and pays for
`The answer is not 70.` and for `The answer is 210. The answer is 70. The answer is 350.` —
both contain the answer, so a substring check cannot tell them from a correct reply.

It is computed per task and category — an empty reply, a denial of the answer, several
answers at once, a malformed reply, a provably wrong answer — and a category is caught on a
task only if every grounded candidate in it was rejected. It always names the categories it
covered and the battery version that defined them, and it is never a safety claim: it says
*these named things were tried, and this many got through*.

## The rule this codebase is built around

> **Bohrin must never falsely accuse a verifier.**

A missed defect costs one finding. A false accusation costs the standard its reason to
exist. So a candidate carries a **ground** — `structural`, `differential` or `invariant` —
only when its wrongness is established without asking the grader, and every guard that stops
a correct answer being called wrong is tested from both directions: a correct grader must
never accept a grounded candidate, and a weak one still must.

## Documentation

| Document | Contents |
|---|---|
| [docs/01_ARCHITECTURE.md](docs/01_ARCHITECTURE.md) | Layout, core types, plugin seam |
| [docs/02_VERIFICATION_GAP.md](docs/02_VERIFICATION_GAP.md) | What the number means and how it is computed |
| [docs/03_PROBES.md](docs/03_PROBES.md) | What is tried, what counts as wrong, and why |
| [docs/04_RELEASE.md](docs/04_RELEASE.md) | What this repository holds, and how it is licensed |

## Not a novelty claim

The techniques are published. The battery is mutation testing with the roles relabelled —
the grader is the test suite, and a surviving mutant is a wrong answer it accepted. What
Bohrin contributes is the discipline around what may be called wrong, written down where
anyone can check it.

## License

[Apache-2.0](LICENSE). Copyright 2026 Bohrin.
