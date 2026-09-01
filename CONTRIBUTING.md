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

Bohrin uses [uv](https://docs.astral.sh/uv/). Python 3.10–3.13 are supported.

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

## Adding a probe

Every probe must justify itself on four points, and a PR that skips any of them will be
asked for it:

1. **Mechanism.** One sentence on *why* this defect degrades a trained policy. Not "this is
   unusual" — "this makes the policy learn X instead of Y."
2. **Evidence.** A public issue, a paper, or a reproducible training run showing the defect
   is real and matters. Plausibility is not evidence.
3. **A fault-injection scenario.** Add it to the benchmark. A registry-enumerating test
   fails the build if any probe lacks one, so this is not optional.
4. **Measured error rates.** The benchmark reports recall and precision. If precision is
   poor, the probe is not ready — raise the threshold or lower the severity.

Detectors register through the `bohrin.probes` entry point, the same mechanism external
plugins use. There is no privileged path for built-ins.

## Pull requests

- **Branch from `main`.** Keep PRs focused; one concern per PR.
- **Write a test that fails before your change and passes after.** For a bug fix, the test
  should encode the bug, not just the fix.
- **Explain the *why* in comments, not the *what*.** The code says what it does.
- **Update `CHANGELOG.md`** under `## [Unreleased]` for anything user-visible.

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
