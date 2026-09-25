# Contributing

Thank you for helping. Bohrin checks other people's graders, so the bar is precision, not breadth:
a submission wrongly called wrong costs more than a defect missed. Everything below follows from
that.

New here? Read [docs/concepts.md](docs/concepts.md) for the ideas and
[ARCHITECTURE.md](ARCHITECTURE.md) for the code map. Both are short.

## The most valuable contribution

**A false positive**: a submission Bohrin calls wrong that is actually correct for your task.
[Report it here](https://github.com/prabhu-gopal/bohrin/issues/new?template=false_positive.yml).
The operator, the task's reference, the submission and why it is correct are enough; you do not
need to share your environment.

## Set up

You need Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/prabhu-gopal/bohrin && cd bohrin
uv sync --extra dev
```

Run `uv sync --extra dev` again whenever `uv.lock` or the entry points in `pyproject.toml`
change, such as after pulling. A plain `uv run` does not install the `dev` extra, and the tests
need it.

## The checks

These are exactly what CI runs, on Python 3.11, 3.12 and 3.13, on Linux and macOS:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

`mypy` runs in strict mode over `src/` and `tests/`. If you touched typing or standard-library
features, run the suite on the oldest supported Python too:
`uv run --extra dev --python 3.11 pytest`.

## What a change needs

**Every change that adds or changes behaviour comes with tests, in the same pull request.** A new
feature, command, probe, rule or format gets tests that exercise it; a bug fix gets a test that
fails before the fix and passes after. A pull request that changes behaviour without a test is not
merged. The table below says what that means for the most common kinds of change.

| If you change… | Also do |
|---|---|
| anything a user can see | an entry in `CHANGELOG.md` under `## [Unreleased]` |
| a rule that stops a false accusation | a test that fails when the rule is removed. Remove it, watch the test fail, put it back |
| a probe or operator | follow [docs/how-to/add-a-probe.md](docs/how-to/add-a-probe.md) |
| the weakness list | follow [docs/how-to/add-a-weakness.md](docs/how-to/add-a-weakness.md), then `uv run python -m bohrin.spec > docs/WEAKNESSES.md` |
| a Coverage Score category | change `BATTERY_VERSION` in `src/bohrin/scoring/coverage.py` |
| `finding.v1.json` | keep it additive, and keep `tests/test_finding.py` green: the schema and the code must refuse the same records |
| a runtime dependency | only if a line in `src/bohrin/` imports it; test-only tools go in the `dev` extra |
| the docs | run `uv run pytest tests/test_docs.py`: it runs the tutorial and checks every link |

### Adding a check: the four things it needs

A check is a claim that a pattern predicts a defect. Each new or changed one needs:

1. **A mechanism**: one sentence on why the defect matters.
2. **Evidence it is real**: a paper, a public write-up or a maintainer's own issue.
3. **Tests in both directions**: no correct grader may accept a grounded submission
   (`tests/test_battery.py`), and a weak grader must still be caught.
4. **Real data**: the real grader you checked it against, every result confirmed by hand.

Describe how a grader fails, never whose. Do not name another project's grader as defective in
code, docs, issues or pull requests unless its maintainers already know.

## Pull requests

- One concern per pull request, branched from `main`. `main` is protected: every change goes
  through a pull request with all CI checks green.
- The description says **what** changed, **why**, and what you ran to **verify** it.
- Sign off every commit (`git commit -s`) under the
  [Developer Certificate of Origin](https://developercertificate.org/). There is no CLA.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Report unacceptable
behaviour to **security@bohrin.com**.
