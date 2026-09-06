# Release notes

One Markdown file per released version of Bohrin, written for **people who use
Bohrin** — not for people reading the source. The website's *Changelog* /
*Releases* page is built from this folder.

If you are looking for the terse, canonical list of every change, that is
[`CHANGELOG.md`](../../CHANGELOG.md) at the repo root. This folder is the
expanded, narrative version of the same information.

---

## Why there are two: `CHANGELOG.md` **and** `docs/releases/`

They answer different questions, for different readers. Every mature project
keeps both.

| | `CHANGELOG.md` (repo root) | `docs/releases/*.md` (this folder) |
|---|---|---|
| **Reader** | a developer reading the repo | someone deciding whether/how to upgrade |
| **Question** | "what changed?" | "what does this release mean for me?" |
| **Style** | terse, one or two sentences per entry, [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) sections | narrative: a TL;DR, upgrade impact, the reasoning, what we verified |
| **Format** | plain Markdown, no frontmatter | Markdown **with YAML frontmatter** so the website can render it |
| **Source of truth for** | the exact set of changes in a tag | how we tell users about a release |

The changelog entry is the seed. The release note is the story grown from it —
same facts, more context, plus the one thing a changelog usually omits:
**do I need to do anything to upgrade?**

## The files

| File | What it is |
|---|---|
| `_template.md` | Copy this to start a new release note. Not published. |
| `unreleased.md` | The running draft for the **next** release. Every user-visible PR adds to it. Rendered on the site with an "unreleased" badge (or only on staging). |
| `X.Y.Z.md` | A shipped release. Frozen the moment the tag is pushed — never edited afterwards (see below). |

Sorting on the website: by `date` in the frontmatter, newest first. Skip
`README.md` and `_template.md`.

## Frontmatter schema

```yaml
---
title: "Bohrin 1.2.0"      # display title
version: "1.2.0"           # bare version, no leading v
date: "2026-11-04"         # ISO date the tag was pushed; "unreleased" file may use the expected date
tag: "v1.2.0"              # the git tag; omit in unreleased.md
breaking: false            # true if this release has any breaking change
summary: >                 # one sentence, shown on the changelog index card
  Adds the OpenEnv adapter and a container execution mode; no breaking changes.
---
```

Keep the keys stable — the website maps them directly. Add a key only when the
site actually needs it.

## Body structure

Use the sections that apply, in this order. They deliberately reuse the
`CHANGELOG.md` vocabulary (`Added` / `Changed` / `Fixed` / `Removed` /
`Known limitations`) so the two documents line up section-for-section.

```markdown
## TL;DR

One short paragraph. What this release is, and whether the reader needs to act.

## Upgrade impact

- **Breaking changes:** none — or a list, each with the migration step
- **Action required:** none — or numbered steps
- **New minimums:** none — or e.g. "Python 3.12", "report schema 2.0"

## Highlights

The 2–5 changes a user actually cares about, most important first, each linking
its PR. This is the part most people read.

## Added / Changed / Fixed / Removed / Known limitations

The fuller list. Mirror the CHANGELOG entry, but you may expand the reasoning
and add examples. Every claim that rests on a number keeps the number — that is
the project's credibility model.

## Verified

What was actually run before the tag went out — the same `bohrin` command a
skeptical reader would run, and what it produced.

## Links

- Full changelog entry: link to the `CHANGELOG.md` heading
- Compare: `vPREV...vTHIS` on GitHub
- PRs in this release: #NN, #NN, …
```

## The rules

1. **Every user-visible PR updates `unreleased.md`** in the same PR — the same
   discipline as `CHANGELOG.md`, and usually the same wording expanded by a
   sentence or two. A PR that only touches internal scaffolding (CI, tests,
   refactors with no observable effect) does not need an entry; when in doubt,
   add one.
2. **A shipped `X.Y.Z.md` is never edited after its tag.** It is the historical
   record of what that tag said to users. If a later release changes something
   described in an old note, the *new* note says so — you do not rewrite the old
   one. (Same rule as `CHANGELOG.md`.)
3. **Write for someone who wasn't in the room.** State the change and the
   reasoning. "Improved detection" is not acceptable; "the determinism probe
   now runs 20 repeats by default, up from 5, because the sweep found 5 missed a
   verifier that flips 5% of the time three times in four" is.
4. **`breaking: true` is load-bearing.** If it is set, the *Upgrade impact*
   section must list every break and its migration step. A breaking change with
   no migration note is an incomplete release note.
5. **The GitHub Release body is a copy of the release note.** When the tag is
   pushed, paste the rendered note (minus frontmatter) into the GitHub Release,
   so people who never visit the website still get it.

## What happens at release time

Part of the maintainer's release checklist — restated here for contributors:

1. `git mv docs/releases/unreleased.md docs/releases/X.Y.Z.md`
2. Fill in the frontmatter: real `date`, add `tag`, finalise `summary` and
   `breaking`.
3. Create a fresh `docs/releases/unreleased.md` from `_template.md`.
4. This happens in the **same PR** as the `version.py` bump and the
   `CHANGELOG.md` `[Unreleased]` → `[X.Y.Z]` rename, so all three move together.
5. After merge and tag, paste the note into the GitHub Release.

## Background reading (best practice this folder follows)

- [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) — the `CHANGELOG.md` format
- [Semantic Versioning](https://semver.org/) — what the version number promises
- [Diátaxis](https://diataxis.fr/) — how the rest of the docs site is organised (this folder is the "explanation/news" corner)
- [Docs as Code](https://www.writethedocs.org/guide/docs-as-code/) — why these live in the repo and change in PRs
