# How to add a probe

A probe is a claim: *this submission is wrong, so a correct grader rejects it*. Adding one means
adding the code that makes the submission, a manifest that describes it, and the tests that keep
it from ever accusing a correct grader. This guide assumes you have read
[concepts.md](../concepts.md) and set up the repository as in [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Before you write code

A probe is accepted only with all four of these. Collect them first, because they decide whether
the probe is worth writing:

1. **A weakness class** it tries, from [WEAKNESSES.md](../WEAKNESSES.md). If none fits, the class
   comes first: see [add-a-weakness.md](add-a-weakness.md).
2. **A mechanism sentence**: why a grader that pays for this submission is wrong, not merely that
   the submission is unusual.
3. **A ground**: why the submission is wrong *without asking the grader*. If you cannot name one,
   the submission is a lead, and a lead-only probe needs a good reason to exist.
4. **Public evidence** that the technique is real: a paper, a public write-up, or a maintainer's own
   issue. A technique goes in only once it is public.

## 1. Write the operator

Operators live in `src/bohrin/mutate/operators.py` and subclass `MutationOperator`:

```python
class ConstantImplementation(MutationOperator):
    """Replace every function body with a constant return (BGW-101)."""

    id = "constant_implementation"
    category = "hollow_program"  # the family of its weakness class
    rationale = "A constant ignores its inputs, so only a grader that checks outputs catches it."
    requires_code = True
    shapes = (Shape.PROGRAM,)

    def apply(self, task: Task) -> Iterator[Candidate]:
        # Yield Candidate(Source(...), Provenance(...), Ground.STRUCTURAL) for each submission,
        # or nothing at all when wrongness cannot be proven for this task.
        ...
```

Rules the operator must follow:

- **Yield nothing when you cannot prove wrongness for this task.** Silence is correct; guessing is
  how false accusations start. For example, a constant-return probe must stay silent when the
  reference itself returns a constant.
- **Claim a ground only for a property of the submission's behaviour.** A difference in source
  text is not evidence of a difference in behaviour.
- **For a workspace probe, write a template.** Use `Workspace(files, commands, parameters)` and
  name what an environment must supply, such as `{test_root}`. Never hard-code a real path.

Register it in `pyproject.toml` under `[project.entry-points."bohrin.mutators"]`, then run
`uv sync --extra dev` so the entry point is installed.

## 2. Write the manifest

Add an entry to `src/bohrin/spec/probes.toml`:

```toml
[[probe]]
id = "bohrin/constant-implementation@1"
operator = "constant_implementation"
weakness = ["BGW-101"]
title = "Every function returns a type-correct constant"
shapes = ["program"]
ground = "structural"
expect = "reject"
maturity = "experimental"
battery = 2
guards = ["The reference itself returns a constant: nothing is submitted."]
sources = ["https://..."]

[probe.template]
solution = "reference-constant"
parameters = []
```

New probes are always `experimental`. If the template needs a new `solution` value, add it to
`SOLUTIONS` in `src/bohrin/spec/probes.py`. `tests/test_probes.py` checks the manifest against
the operator: the same shapes, the same ground, and the category of its weakness's family.

## 3. Write the tests, in both directions

In `tests/test_operators.py` and `tests/test_battery.py`:

- **A correct grader is never accused.** Build a grader in `tests/_fixtures.py` style that is
  right to accept everything it accepts, and assert that no grounded candidate from your probe is
  accepted. This is the test that matters most.
- **A weak grader is still caught.** Assert that the grader with the gap your probe targets does
  accept a grounded candidate. Otherwise a guard may simply have switched the probe off.
- **Every guard you add fails its test when removed.** Delete the guard, run the tests, see one
  fail, put it back.

## 4. Check it on a real grader

Run the probe against at least one real, public grader and confirm every result by hand. Keep the
evidence with your pull request. If a result is about someone else's grader, describe the
mechanism, never the project, until its maintainers have been told.

## 5. Update the public record

- Add the probe to the table in [SPEC.md](../SPEC.md) ("What is tried").
- If it adds, removes or redefines a category, change `BATTERY_VERSION` in
  `src/bohrin/scoring/coverage.py`, because scores are comparable only within one battery.
- Add a line to `CHANGELOG.md` under `## [Unreleased]`.
- Run the full check: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`.

## Publishing a probe from your own package instead

You do not need to change this repository to use a probe. Subclass `MutationOperator` in your own
package and register it under the `bohrin.mutators` entry point; `battery()` will run it with the
same rules as a built-in one. Use your own namespace for its ID (`acme/constant-implementation@1`).
