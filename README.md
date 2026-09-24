# bohrin

[![CI](https://github.com/prabhu-gopal/bohrin/actions/workflows/ci.yml/badge.svg)](https://github.com/prabhu-gopal/bohrin/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/bohrin.svg)](https://pypi.org/project/bohrin/)
[![Python](https://img.shields.io/pypi/pyversions/bohrin.svg)](https://pypi.org/project/bohrin/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Check the checker.** Bohrin is an open standard and Python library for testing the graders
of reinforcement-learning environments: the verifiers, reward functions and test suites that
decide whether a model's work counts. It finds where a grader pays for work that was not done,
and it proves every such finding without trusting the grader it is testing.

## Why this exists

Every AI system has something that decides whether it did well. In training it is a grader. At
release it is a benchmark. For a coding agent it is a test suite. Those checkers decide what
models learn, which scores get published and what code ships. They are trusted by everyone and
checked by almost no one.

When a grader can be passed without doing the task, a model trained against it learns to pass
it that way. This is **reward hacking**, and it is not rare: published audits of widely used
agent benchmarks have reached near-perfect scores without solving a single task, and studies
of frontier models have caught them rewriting tests, exiting before the checks run and
special-casing the visible inputs. The fix starts before training, with the grader.

## What it does today

Bohrin gives you the submissions a correct grader must reject, each one wrong by construction,
and scores how many your grader caught.

```console
$ pip install bohrin
```

```python
from bohrin.ir.task import Task
from bohrin.mutate.battery import battery
from bohrin.scoring.coverage import Attempt, coverage_score

reference = "def add(a, b):\n    return a + b\n"
task = Task(id="add", prompt="Write add(a, b) that returns the sum.", reference=reference)


def my_grader(task, submission):
    # A common weak shape: checks that the function exists and runs, not what it returns.
    namespace = {}
    try:
        exec(submission, namespace)
        namespace["add"](2, 3)
        return True
    except Exception:
        return False


attempts = [
    Attempt(task.id, candidate, accepted=my_grader(task, candidate.payload.text))
    for candidate in battery(task).candidates
]
print(coverage_score(attempts))
```

```console
COVERAGE SCORE: 0 / 100   95% CI 0–79   0 of 1 caught   categories: 1 of 5 (battery 2)
```

That grader pays for the reference with every function body replaced by `pass`: the emptied
code still runs, so the grader never notices that it returns nothing. The score says exactly
how much was tried, one submission in one of five categories, and its interval is wide
because one submission is a small sample.

Every submission targets a class in the [weakness list](docs/WEAKNESSES.md), which names every
published way a coding grader or its harness can be cheated, and counts towards the category
named after that class's family:

| Category | Ways of passing without doing the work |
|---|---|
| `hollow_program` | code that does no work: empty or constant bodies, an early exit, spoofed equality |
| `harness_tampering` | a submission that changes what judges it: test hooks, edited tests, a written reward |
| `answer_access` | a solution obtained instead of produced: read from the environment or from history |
| `weak_tests` | a wrong program or output that the tests or the checker cannot tell from a right one |
| `grader_logic` | a failure the grader scores as success |

Two numbers come out of it:

- **The Coverage Score** (0–100, higher is better): of the known ways a task can be passed
  without doing it, the share your grader caught, with its sample and a 95% Wilson interval.
- **The Verification Gap** (0–100, lower is better): how often a grader paid for work that was
  wrong or disagreed with itself, printed with the checks it covered.

## Principles

These hold for every check Bohrin contains now and every check it adds later.

1. **No accusation without proof.** A submission is called wrong only when that is established
   without asking the grader under test: it does no work by construction, it differs provably
   from the declared answer, or it contradicts the task's own ground truth. Anything else is a
   **lead**: tried and shown to you, never counted.
2. **Every number carries its uncertainty.** A score is printed with its sample, its interval
   and the version of the checks behind it, because `2 of 2` and `300 of 300` must never read
   the same.
3. **What was not checked is said out loud.** A check that could not run is reported as not
   measured, never as clean. A clean result means these checks found nothing, not that the
   grader is safe.
4. **The method is open.** The rules, the grounds and the scoring are in
   [docs/SPEC.md](docs/SPEC.md), so anyone receiving a Bohrin result can recompute it and argue
   with it.
5. **Nothing here is new, on purpose.** Mutation testing, metamorphic testing and adversarial
   search are decades old. What Bohrin adds is the discipline: proof before accusation, and a
   standard others can measure against.

## Scope

Bohrin starts with the graders of **RL coding environments**, which decide whether a program,
a patch or a change to a repository solved its task. The same rules are written to carry
further: to benchmarks, to the tests coding agents change, and to any checker whose verdict
someone else relies on. They extend one kind of checker at a time, and only as far as proof
can follow.

## Extending it

Operators (new known-wrong submissions) and relations (new certified rewritings of a correct
solution) register through the public `bohrin.mutators` and `bohrin.relations` entry points,
from your own package, with no fork. Third-party code is held to exactly the same rules as
built-in code. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing

The most valuable contribution is a **false positive**: a submission Bohrin calls wrong that is
actually correct for your task.
[Report one here](https://github.com/prabhu-gopal/bohrin/issues/new?template=false_positive.yml).
You do not need to share your environment.

Security issues: see [SECURITY.md](SECURITY.md). Bohrin makes no network calls and sends no
telemetry.

## Citing

If Bohrin helps your research, please cite it using [CITATION.cff](CITATION.cff), or GitHub's
"Cite this repository" button.

## License

[Apache-2.0](LICENSE).
