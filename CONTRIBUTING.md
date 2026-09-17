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

This repository holds one complete job: checking a grader you own, on your machine (see
[docs/04_RELEASE.md](docs/04_RELEASE.md#the-boundary)). Contributions that make that job better
are welcome:

- **Accuracy.** A false positive report is the most valuable thing you can send. So is a relation
  that stops a correct answer being mistaken for a wrong one, or a fix to how wrongness is
  established.
- **New fixed checks** that are deterministic and need no model: a payload that is wrong by
  construction, a check that reads version history or a trace file you already have on disk.
- **Adapters** for the places graders and evaluations are written.
- **Report renderers, documentation and bug fixes.**

Every check, new or changed, carries the same burden:

1. **Mechanism.** One sentence on why this defect matters, not that it is unusual.
2. **Evidence.** A public issue, a paper, or a reproducible run showing it is real.
3. **A test that fails before your change and passes after**, plus the clean fixture staying
   clean: any finding there fails the build.
4. **Real data.** Say which real target you ran it against, and confirm every finding by hand.

**What belongs elsewhere:** adaptive or model-driven search for cheats, connectors into systems
Bohrin does not run, holding actions at runtime, team history, and certificate issuance. Those are
different jobs and they are not part of this repository. You are free to publish your own plugin
for any of them: probes, adapters, operators and relations all register through public entry
points (`bohrin.probes`, `bohrin.adapters`, `bohrin.mutators`, `bohrin.relations`) with no
privileged path for built-ins. A plugin that reports a finding must still establish wrongness
independently of the verifier under audit, or it produces leads, not findings — see
[docs/03_PROBES.md](docs/03_PROBES.md).

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
