# bohrin

[![CI](https://github.com/prabhu-gopal/bohrin/actions/workflows/ci.yml/badge.svg)](https://github.com/prabhu-gopal/bohrin/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Check the grader of an RL coding environment before you train on it.**

In a coding environment, a grader decides whether each submission solved the task, and it is
the only thing the model learns from. If it pays for code that does not do the work, the model
learns to not do the work.

Bohrin gives you the submissions a correct grader must reject — each one wrong by construction —
and scores how many your grader caught.

## Install

```console
$ pip install bohrin
```

## Use

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
    Attempt(task.id, candidate, accepted=my_grader(task, candidate.payload)) for candidate in battery(task).candidates
]
print(coverage_score(attempts))
```

```console
COVERAGE SCORE: 75 / 100   95% CI 30–95   3 of 4 caught   categories: 4 of 5 (battery 1)
```

That grader rejects an empty submission, a truncated reply and a constant, and pays for the
reference with every function body replaced by `pass` — it runs, so the grader never notices it
returns nothing.

## What is tried

| Category | Submissions |
|---|---|
| `empty_and_echo` | an empty submission, the task prompt echoed back, a refusal |
| `wrong_answer` | a constant (`0`, `None`, `[]` …), the reference with every function body emptied |
| `malformed_output` | a repetition loop, and a reply cut off inside unclosed markup |
| `denial` | an explicit denial of the declared answer |
| `multiple_answers` | several answers at once, the declared one among them |

A submission is called wrong only when that is established without asking your grader. One that
cannot be shown to be wrong — a refusal on a task with no declared answer, say — is a **lead**:
tried and shown to you, never counted. See [docs/SPEC.md](docs/SPEC.md) for the exact rules.

## License

[Apache-2.0](LICENSE).
