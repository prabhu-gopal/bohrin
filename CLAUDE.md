# Working on bohrin — the house rules

This file is the persistent playbook for this repo. Read it before making any change,
opening a PR, or touching a release. It exists so the workflow survives across sessions —
you should be able to pick this repo back up with zero prior context and still do the
right thing.

## The one rule above all the others

**`main` is protected. Nobody pushes to it directly — not even the owner.**

Every change, no matter how small, goes through a branch + pull request. This was verified
working (a direct push to `main` was tested and rejected by GitHub) — it is not optional or
aspirational. If a `git push origin main` is ever refused with "protected branch update
failed," that is the protection working correctly, not a bug to route around.

## Never do this

- **Never add a "Co-Authored-By: Claude" (or any AI attribution) trailer to a commit.**
  Every commit in this repo is authored as Prabhu Gopal, full stop. This applies
  regardless of what a tool's default commit-message template suggests.
- **Never `git push --force` to `main`**, and never try to, even to "fix" something — branch
  protection blocks force-pushes and deletions on `main` by design.
- **Never commit or push `docs/`.** It is `.gitignore`'d on purpose — it holds internal
  business-strategy notes (open-core reasoning, roadmap, licensing analysis) that stay
  local. If you find yourself about to `git add docs/`, stop and check `.gitignore` first.
- **Never bypass CI to merge faster.** All 9 required checks (see below) must be green.
- **Never publish to PyPI by hand.** Publishing happens by pushing a `vX.Y.Z` git tag, which
  triggers `.github/workflows/release.yml`. There is no local `twine upload` path, and
  there should never be one — Trusted Publishing is the only route, by design.

## How to make any change

```bash
git checkout main && git pull origin main       # start from a clean, current main
git checkout -b <short-descriptive-branch-name>  # e.g. fix-dead-dimension-off-by-one
# ... make the change ...
```

Before committing, every one of these must be clean — this is exactly what CI checks, so
catching it locally first saves a round-trip:

```bash
ruff check .
ruff format --check .
mypy
pytest -q
```

If you touched anything Python-version-sensitive (typing, numpy dtypes, stdlib features),
don't trust a single local interpreter — `mypy`'s target version comes from whatever
Python runs it, so a laptop on 3.13 can pass locally while 3.10 fails in CI. Verify against
a real 3.10 interpreter before pushing if there's any doubt:

```bash
uv run --extra dev --python 3.10 pytest -q
uv run --extra dev --python 3.10 mypy
```

Then commit and open the PR:

```bash
git add -A
git commit -m "One line: what changed and why, not just what"
git push -u origin <branch-name>
gh pr create --fill        # or --title/--body for a fuller description
```

### What a good PR description says

Look at PR #1 and #2 in this repo's history for the pattern. Every PR body answers three
things, briefly:

1. **What** changed, in one or two sentences.
2. **Why** — the actual reasoning, not just "improves X." If a change is based on measured
   evidence (a benchmark, a real-data sweep, a reproduced CI failure), say what was
   measured and what the numbers were. "Deleted detector because it seemed redundant" is
   not acceptable; "excluded because it reported HIGH on 70% of 20 real datasets, see
   scripts/hub_smoke.py" is.
3. **Verified** — what you actually ran to confirm it works, not just "should work."

### Merging

Once all 9 required CI checks are green (see below), merge via `gh pr merge --squash` or
the GitHub UI. Delete the branch after merging — don't let merged branches accumulate:

```bash
git checkout main && git pull origin main
git branch -d <branch-name>
git push origin --delete <branch-name>
```

## The 9 required CI checks (branch protection will not let a PR merge without all green)

From `.github/workflows/ci.yml`:

- `installed-wheel smoke test`
- `py3.10 · ubuntu-latest`, `py3.10 · macos-latest`
- `py3.11 · ubuntu-latest`, `py3.11 · macos-latest`
- `py3.12 · ubuntu-latest`, `py3.12 · macos-latest`
- `py3.13 · ubuntu-latest`, `py3.13 · macos-latest`

Each runs lint, format-check, `mypy --strict`, and the full test suite. The exact names
matter — if a CI job is ever renamed, branch protection's required-checks list on GitHub
(Settings → Branches → main) has to be updated to match, or the old name just sits there
forever "pending" and blocks every future merge.

## Adding or changing a detector

A detector is not just code — it's a claim that a specific pattern in the data predicts a
specific training failure. Every new or changed detector needs, before it's considered
done (this mirrors `CONTRIBUTING.md`, restated here because it's the thing most likely to
be skipped under time pressure):

1. **A mechanism sentence** — *why* this defect degrades a trained policy, not just that
   it's statistically unusual.
2. **A fault-injection scenario** added to the benchmark. A registry-enumerating test fails
   the build if any detector lacks one — this is enforced, not a suggestion.
3. **Real-data validation before trusting its default severity.** `scripts/hub_smoke.py`
   scans a fixed set of 20 real public LeRobot datasets and prints, per detector, how often
   it fires and how often it fires at HIGH. Run it after adding or changing a detector's
   threshold logic:

   ```bash
   python scripts/hub_smoke.py --json /tmp/sweep.json
   ```

   A detector reporting HIGH on more than roughly half of curated public datasets is far
   more likely to have a threshold bug than to have found a real epidemic — see the
   worked example below.

### `DEFAULT_EXCLUDED` — the precedent for "this detector isn't trustworthy by default yet"

`src/bohrin/detectors/registry.py` defines `DEFAULT_EXCLUDED`: detector IDs that exist,
are fully implemented and benchmarked, but are held back from a default `bohrin scan`
pending recalibration, reachable with `--all`. This is not a place to quietly hide a
detector you don't like — it exists because two specific detectors were *measured*
(via `scripts/hub_smoke.py`) reporting HIGH on 60-70% of real datasets, and further shown
to land in the report's visible top-6 findings 13 of 16 times they fired. If you add a
detector to this set, the commit message and the `DEFAULT_EXCLUDED` docstring both need
the actual numbers behind the decision — not "seems noisy."

Never delete a detector to solve a noise problem. If a detector is unreliable, the fix is
either (a) fix its threshold logic, using real data to verify the fix, or (b) add it to
`DEFAULT_EXCLUDED` with the evidence documented. Deleting tested, benchmarked code to
"simplify" is a regression, not a cleanup — this project has been burned by that exact
recommendation once already (a reviewer proposed cutting 48 detectors to 3; the actual fix
for the real problem they'd identified turned out to be the `DEFAULT_EXCLUDED` mechanism,
not deletion).

## Maintaining `CHANGELOG.md`

Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/):

- **Every user-visible change gets an entry under `## [Unreleased]`**, in the same PR that
  makes the change — not batched up later from memory. Use the existing subsections
  (`### Added`, `### Changed`, `### Fixed`, `### Known limitations`, `### Deliberately not
  included`) as they fit; add a new one if none fits.
- **Never edit a changelog section for a version that's already tagged and released.**
  `[0.1.0]`'s entry is a historical record of what that exact tag contained — if a later
  change affects something described there (e.g. a detector's default behavior changes),
  add a new entry under `[Unreleased]` that says so, rather than rewriting history.
- When a release is actually tagged, rename `## [Unreleased]` to `## [X.Y.Z] — <date>`,
  add a fresh empty `## [Unreleased]` above it, and update the comparison links at the
  bottom of the file.
- Write entries for a reader who wasn't in the room: state the behavior change and the
  reasoning in one or two sentences, the way the existing entries do. If a number backs the
  claim (a measured rate, a benchmark result), include it — that's this project's whole
  credibility model.

## Releasing (tagging a new version)

Never publish by hand; the only path is a git tag:

```bash
git checkout main && git pull origin main   # main, post-merge, is what ships
# bump src/bohrin/version.py's __version__
# move CHANGELOG.md's [Unreleased] section to a new [X.Y.Z] entry (see above)
git add src/bohrin/version.py CHANGELOG.md
git commit -m "Bump version to X.Y.Z"
# this commit also needs a PR + merge — main is protected, version bumps are no exception
git tag -a vX.Y.Z -m "bohrin X.Y.Z" -m "<changelog entry for this version>"
git push origin vX.Y.Z
```

Pushing the tag triggers `release.yml`: builds the wheel + sdist, verifies the wheel
actually contains the `bohrin/` package, publishes to PyPI via Trusted Publishing
(`id-token: write`, no stored secrets), and attaches the artifacts to a GitHub release.

**Before trusting a release actually works**, install it from a machine/venv that's never
touched this codebase and run the real command:

```bash
python -m venv /tmp/verify && /tmp/verify/bin/pip install bohrin
/tmp/verify/bin/bohrin scan lerobot/pusht
```

If that doesn't produce a correct finding in well under 15 seconds (network-bound; a few
seconds warm), the release is not actually done, whatever CI says.

Dry-run first on TestPyPI when in doubt: `gh workflow run release.yml -f test_pypi=true`
(needs the `testpypi` pending publisher configured on test.pypi.org — see PyPI account
settings, not anything in this repo).

## Where the real detail already lives — don't duplicate it here

- `CONTRIBUTING.md` — dev setup, DCO sign-off, PR checklist for human contributors.
- `SECURITY.md` — how to report a vulnerability, response SLA.
- `README.md` — what the tool does, what it doesn't, supported formats.
- `scripts/hub_smoke.py` — the real-data validation harness; its own docstring explains
  when and why to run it.
- `pyproject.toml` — dependency policy is enforced by evidence, not habit: don't add a
  dependency that isn't imported by a line of code yet, and don't leave one in `dependencies`
  if `grep -rn "^import X\|^from X" src/bohrin/` comes back empty (see the scipy removal in
  this repo's history for the worked example — it was declared but never actually imported).
