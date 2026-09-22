## What does this change?

<!-- One or two sentences. The "why" matters more than the "what". -->

## Why?

<!-- What problem does this solve? Link the issue if there is one. -->

## Checklist

- [ ] Commits are signed off (`git commit -s`) — see [CONTRIBUTING.md](../CONTRIBUTING.md)
- [ ] `ruff check .`, `mypy`, and `pytest` pass locally
- [ ] Added a test that fails before this change and passes after
- [ ] Updated `CHANGELOG.md` under `## [Unreleased]` if this is user-visible

### If this adds or changes an operator or relation

- [ ] The mechanism sentence says *why* the defect degrades a trained policy
- [ ] Linked evidence that the defect is real (issue, paper, or reproducible run)
- [ ] Added a correct grader to `tests/test_battery.py` that no grounded candidate may be accepted by
- [ ] Added a weak grader that must still accept a grounded candidate
