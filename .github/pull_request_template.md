## What does this change?

<!-- One or two sentences. -->

## Why?

<!-- What problem does this solve? If it rests on a measurement, say what was measured and the numbers. -->

## How was it verified?

<!-- What you actually ran, not "should work". -->

## Checklist

- [ ] Commits are signed off (`git commit -s`). See [CONTRIBUTING.md](../CONTRIBUTING.md)
- [ ] `ruff check .`, `ruff format --check .`, `mypy` and `pytest` pass locally
- [ ] Added a test that fails before this change and passes after
- [ ] Updated `CHANGELOG.md` under `## [Unreleased]` if this is user-visible

### If this adds or changes a probe, a rule or a weakness class

- [ ] Followed [add-a-probe](../docs/how-to/add-a-probe.md) or [add-a-weakness](../docs/how-to/add-a-weakness.md)
- [ ] The mechanism sentence says *why* the defect matters
- [ ] Linked public evidence that the technique is real, and read the passage that supports it
- [ ] A correct grader is never accused, and a weak grader is still caught (both tested)
- [ ] Every new guard fails its test when removed
