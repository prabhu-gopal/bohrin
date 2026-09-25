# Tutorial: check your first grader

In about ten minutes you will generate the submissions a correct grader must reject, run two
graders on them (one weak, one correct), score both, and look up what the weak one got wrong.
You need Python 3.11 or newer and basic Python. No knowledge of Bohrin is assumed; the ideas are
explained in [concepts.md](concepts.md) if you want them first.

Every code block on this page runs, and the output shown under it is exactly what it prints. The
test suite checks that, so the page cannot drift from the code.

## 1. Install

```console
$ pip install bohrin
```

## 2. Describe a task

A task is an ID, the prompt the model saw, and a reference solution you know is correct.

```python
from bohrin.ir.task import Task

reference = "def add(a, b):\n    return a + b\n"
task = Task(id="add", prompt="Write add(a, b) that returns the sum.", reference=reference)
print(task.shape)
```

```text
program
```

Its shape is `program`: its grader takes source code and returns a verdict. That is the default.

## 3. Build the battery

The battery is every submission a correct grader must reject for this task. Each one says which
probe made it and the ground that makes it wrong.

```python
from bohrin.mutate.battery import battery

result = battery(task)
for candidate in result.candidates:
    print(candidate.provenance.operator, candidate.ground)
    print(candidate.payload.text)
```

```text
drop_side_effect structural
def add(a, b):
    pass
```

The reference with its body replaced by `pass` keeps the signature and does no work, so its
wrongness is *structural*: it holds by construction, without asking any grader.

## 4. Run two graders on it

Bohrin never runs your grader; you do. Here are two small ones. The first only checks that the
function exists and runs, a common weak shape. The second checks what it returns.

```python
def runs_it(submission):
    namespace = {}
    try:
        exec(submission, namespace)
        namespace["add"](2, 3)
        return True
    except Exception:
        return False


def checks_it(submission):
    namespace = {}
    try:
        exec(submission, namespace)
        return namespace["add"](2, 3) == 5 and namespace["add"](-1, 1) == 0
    except Exception:
        return False


for grader in (runs_it, checks_it):
    print(grader.__name__, [grader(c.payload.text) for c in result.candidates])
```

```text
runs_it [True]
checks_it [False]
```

`runs_it` paid for code that does nothing. `checks_it` refused it.

> Never `exec` untrusted code outside a sandbox. It is safe here only because every submission
> comes from your own reference.

## 5. Score them

The Coverage Score is the share of the battery a grader rejected, with its uncertainty.

```python
from bohrin.scoring.coverage import Attempt, coverage_score

for grader in (runs_it, checks_it):
    attempts = [Attempt(task.id, c, accepted=grader(c.payload.text)) for c in result.candidates]
    print(coverage_score(attempts))
```

```text
COVERAGE SCORE: 0 / 100   95% CI 0–79   0 of 1 caught   categories: 1 of 5 (battery 2)
COVERAGE SCORE: 100 / 100   95% CI 21–100   1 of 1 caught   categories: 1 of 5 (battery 2)
```

Read the whole line, not just the number:

- **`95% CI 21–100`**: one submission is a small sample, so a perfect score is still uncertain.
  Two out of two and three hundred out of three hundred must never read the same.
- **`categories: 1 of 5`**: only one of the five categories was measured for this task. The other
  four were not tried, and a category that was not tried is never counted as caught.
- **`battery 2`**: scores are comparable only within the same battery version.

## 6. Check that it still accepts correct work

A grader that rejects everything catches every cheat. So the Coverage Score has a second number
beside it: **correct-work acceptance**, the share of *correct* submissions the grader accepted.
Bohrin makes them from your reference: the reference itself, then rewritings of it that are
proved, by machine, to do exactly the same thing. This task's reference has a comment and a local
variable, so there is something to rewrite:

```python
from bohrin.relations import positive_controls

reference = "def add(a, b):\n    total = a + b  # the sum\n    return total\n"
task = Task(id="add", prompt="Write add(a, b) that returns the sum.", reference=reference)

for control in positive_controls(task):
    print(control.relation)
    print(control.payload.text)
```

```text
oracle
def add(a, b):
    total = a + b  # the sum
    return total

comment_free
def add(a, b):
    total = a + b
    return total

renamed_locals
def add(a, b):
    local_0 = a + b
    return local_0

```

`oracle` is the reference unchanged. It is the baseline: if a grader rejects it, the task is left
out of both numbers, because a grader that fails the reference is not measuring the task.

Now score `checks_it` beside a grader that accepts only the reference's exact text:

```python
from bohrin.scoring.scorecard import ControlAttempt, scorecard


def matches_reference(submission):
    return submission == reference


for grader in (checks_it, matches_reference):
    attempts = [Attempt(task.id, c, accepted=grader(c.payload.text)) for c in battery(task).candidates]
    controls = [ControlAttempt(task.id, c, accepted=grader(c.payload.text)) for c in positive_controls(task)]
    print(grader.__name__)
    print(scorecard([task], attempts, controls))
```

```text
checks_it
program: 1 task scored
  COVERAGE SCORE: 100 / 100   95% CI 21–100   1 of 1 caught   categories: 1 of 5 (battery 2)
  CORRECT-WORK ACCEPTANCE: 100 / 100   95% CI 34–100   2 of 2 accepted   relations: 2
  not run: 15 applicable weakness classes: BGW-102, BGW-103, BGW-104, BGW-105, BGW-106, BGW-107, BGW-119, BGW-121, BGW-122, BGW-123, BGW-125, BGW-126, BGW-127, BGW-128, BGW-137
matches_reference
program: 1 task scored
  COVERAGE SCORE: 100 / 100   95% CI 21–100   1 of 1 caught   categories: 1 of 5 (battery 2)
  CORRECT-WORK ACCEPTANCE: 0 / 100   95% CI 0–66   0 of 2 accepted   relations: 2
  not run: 15 applicable weakness classes: BGW-102, BGW-103, BGW-104, BGW-105, BGW-106, BGW-107, BGW-119, BGW-121, BGW-122, BGW-123, BGW-125, BGW-126, BGW-127, BGW-128, BGW-137
```

Both catch the empty body, but `matches_reference` rejects every correct rewriting: it checks the
text, not what the code does. The two numbers are never merged, because any single number made
from them could be raised by trading one for the other. The `not run` line names every weakness
class that applies to this kind of grader and that nothing here tried.

## 7. Look up what went wrong

Every probe points at a weakness class, and every class has a permanent ID and fix guidance.

```python
from bohrin.spec import probe_for, weakness_list

probe = probe_for("drop_side_effect")
print(probe.id, "tries", probe.weakness)

weakness = weakness_list().get(probe.weakness[0])
print(weakness.id, weakness.name)
print(weakness.fix)
```

```text
bohrin/empty-implementation@1 tries ('BGW-101',)
BGW-101 Trivial implementation
Check return values against known outputs on inputs the submission cannot see, and include at least one case a constant or empty body cannot pass.
```

That is the fix for `runs_it`, and `checks_it` already follows it.

## Where next

- [concepts.md](concepts.md): the ideas behind this: grounds, leads, templates, findings.
- [WEAKNESSES.md](WEAKNESSES.md): all 38 weakness classes, with their sources and fixes.
- [SPEC.md](SPEC.md): the exact rules behind every number.
- [How to add a probe](how-to/add-a-probe.md), if you want to contribute one.
