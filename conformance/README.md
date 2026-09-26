# Conformance suite

Fixture graders with known defects, for proving that a grader-checking tool is sound: it flags
every grader with a defect, and never flags a correct one. Any tool can use the suite, Bohrin or
not. The rules are in [docs/SPEC.md](../docs/SPEC.md#conformance).

## What is here

`bcl-1/` holds the fixtures of level **BCL-1** (grader shapes `program` and `io`). Each weakness
has a pair of graders:

- `<weakness>-correct.py`, which grades correctly;
- `<weakness>-defect.py`, which has exactly that one defect.

The expected result for every fixture, and the weakness each pair is about, are in
[`src/bohrin/conformance/bcl-1.toml`](../src/bohrin/conformance/bcl-1.toml).

| Weakness | Pair |
|---|---|
| BGW-101 Trivial implementation | `trivial-implementation` |
| BGW-102 Exit before the checks | `exit-before-checks` |
| BGW-103 Equality spoofing | `equality-spoofing` |
| BGW-104 Hard-coded expected outputs | `hard-coded-outputs` |
| BGW-105 State recorded across calls | `state-across-calls` |
| BGW-120 Tests too narrow | `tests-too-narrow` |
| BGW-123 Output checker too lenient | `lenient-checker` |
| BGW-124 Reference solution wrong | `reference-wrong` |
| BGW-126 Failure scored as success | `failure-scored-as-success` |
| BGW-127 Nondeterministic grader | `nondeterministic-grader` |

Every weakness of BCL-1 has a pair, so a level achieved on this version of the suite is achieved
over all ten.

The `exit-before-checks` pair runs the program in a child process, because that is where an exit
status can be mistaken for a verdict. The correct one passes a program only when the child prints,
after the last check, a token handed to it on standard input before the program runs.

## The grader interface

Every fixture is one self-contained Python file using only the standard library. The first line
of its docstring says what it is, and the docstring states the task and, for a defective grader,
the defect.

- **`program` shape:** `grade(submission: str) -> float`. `submission` is a program's source
  defining `solve(items)`. The grader runs it and returns 1.0 for a pass and 0.0 for a fail.
- **`io` shape:** `grade(output: str) -> float`. `output` is what a program printed for the
  input in the file's `INPUT`.

The graders run the code they are given. Load them only inside whatever isolation your tool uses
for any grader.

## Reporting results

Run your tool on every fixture and write one JSON document in the
[`conformance-results/v1`](../src/bohrin/conformance/conformance-results.v1.json) format:

```json
{
  "$schema": "https://bohrin.com/schema/conformance-results/v1",
  "suite": {"level": "BCL-1", "version": 1},
  "tool": {"name": "your-tool", "version": "1.2.0"},
  "results": [
    {"fixture": "bcl-1/trivial-implementation/defect", "status": "ran", "flagged": ["BGW-101"]},
    {"fixture": "bcl-1/trivial-implementation/correct", "status": "ran", "flagged": []},
    {"fixture": "bcl-1/lenient-checker/correct", "status": "skipped", "message": "io graders not supported"}
  ]
}
```

`status` is `ran` (then `flagged` lists every weakness class the tool reported, and may be
empty), `error` or `skipped`. Then:

```console
$ bohrin conformance check results.json
```

It runs no grader. It compares your results with the expected ones, prints the level achieved
and exits 0 when it is achieved, 1 when it is not, and 2 when the file cannot be checked.

## Licence

Every fixture was written for this suite and is Apache-2.0 like the rest of the repository. No
problem text or grader is copied from another dataset.
