# Contributing

The bar is precision, not breadth: a submission wrongly called wrong costs more than a defect
missed.

## The most valuable contribution

**A false positive.** If a grounded submission is actually a correct answer for your task, open
an issue with the
[false positive template](https://github.com/prabhu-gopal/bohrin/issues/new?template=false_positive.yml).
The operator, the declared answer, the submission and why it is correct are enough.

## Setup and checks

```bash
git clone https://github.com/prabhu-gopal/bohrin && cd bohrin
uv sync --extra dev
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

These are exactly what CI runs.

## Adding an operator or a rewriting

Each needs:

1. **Mechanism.** One sentence on why the defect it catches matters.
2. **Evidence.** A public issue, a paper, or a reproducible run.
3. **A test that fails before and passes after**, with `tests/test_battery.py` staying green: no
   correct grader may accept a grounded submission.
4. **Real data.** The real grader you checked it against, every result confirmed by hand.

Operators and rewritings can also be published as your own package through the
`bohrin.mutators` and `bohrin.relations` entry points. The rules in
[docs/SPEC.md](docs/SPEC.md) apply to them too.

## Pull requests

- One concern per pull request, branched from `main`.
- User-visible changes get an entry in `CHANGELOG.md` under `## [Unreleased]`.
- Sign off your commits (`git commit -s`) under the
  [Developer Certificate of Origin](https://developercertificate.org/). There is no CLA.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Report unacceptable
behavior to **security@bohrin.com**.
