# Contributing to Bohrin

Thanks for considering it. Bohrin's whole value is that its findings are trustworthy, so
the bar here is precision, not breadth: a probe that is right 95% of the time is worth
more than five that are right 70% of the time.

## The most valuable contribution

**A false positive report.** If bohrin flagged something on your data that is actually
fine, that is the single most useful thing you can send us — it is how probe thresholds
get calibrated. Use the
[false positive template](https://github.com/prabhu-gopal/bohrin/issues/new?template=false_positive.yml).
You do not need to share the environment; the finding, the probe id, and why it is wrong is
plenty.

## Setup

Bohrin uses [uv](https://docs.astral.sh/uv/). Python 3.11–3.13 are supported.

```bash
git clone https://github.com/prabhu-gopal/bohrin
cd bohrin
uv sync --extra dev
```

Or with plain pip:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the checks

These three are exactly what CI runs. If they pass locally, they pass there.

```bash
ruff check .          # lint
ruff format --check . # formatting
mypy                  # strict type checking, src and tests
pytest                # the full suite; no network, no GPU
```

The test suite runs entirely on synthetic fixtures, so it needs no environment and no network.
It should finish in well under a minute.

## What this repository accepts

The released checks — four probes, nine operators and seventeen answer relations — are the
open check set, and it is complete as shipped (see
[docs/04_RELEASE.md](docs/04_RELEASE.md#how-the-open-check-set-changes)). The most useful
contributions are:

- **Accuracy.** A false positive report, a relation that stops a correct answer being
  mistaken for a wrong one, or a fix to how wrongness is established. Every change here needs
  a test that fails before it and passes after, and a real environment it was checked on.
- **Adapters and integrations** for the places graders are written.
- **Report renderers and bug fixes.**

**New probes and operators** are not merged here. Publish them as your own package: they
register through the `bohrin.probes` and `bohrin.mutators` entry points, the same mechanism
the built-in checks use, with no privileged path. A plugin that reports a finding must still
establish wrongness independently of the verifier under audit, or it produces leads, not
findings — see [docs/03_PROBES.md](docs/03_PROBES.md).

## Pull requests

- **Branch from `main`.** Keep PRs focused; one concern per PR.
- **Write a test that fails before your change and passes after.** For a bug fix, the test
  should encode the bug, not just the fix.
- **Explain the *why* in comments, not the *what*.** The code says what it does.
- **Document anything user-visible, in the same PR**, in two places:
  - `CHANGELOG.md` under `## [Unreleased]` — the terse, canonical entry.
  - `docs/releases/unreleased.md` — the narrative version that feeds the website's
    changelog page. Usually the same wording, expanded by a sentence or two of
    context. See [`docs/releases/README.md`](docs/releases/README.md) for the format.

  A PR that only touches internal scaffolding (CI, tests, a refactor with no
  observable effect) needs neither. When in doubt, add both.

## Sign your commits (DCO)

Bohrin uses the [Developer Certificate of Origin](https://developercertificate.org/).
There is no CLA — you keep the copyright to what you write.

Signing off means you certify you wrote the code, or have the right to submit it under
Apache-2.0. Add `-s` to every commit:

```bash
git commit -s -m "Add a thing"
```

That appends a line like `Signed-off-by: Your Name <you@example.com>` to the message. The
DCO bot checks every commit in a PR. If you forgot on the last one:

```bash
git commit --amend -s --no-edit && git push --force-with-lease
```

For a whole branch:

```bash
git rebase --signoff main && git push --force-with-lease
```

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Report unacceptable
behavior to **security@bohrin.com**.
