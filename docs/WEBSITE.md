# Docs handoff — for the website team

Everything the site build needs to render the **Docs** and **Changelog**
sections from this repository. This is the contract between the repo and the
site: if it changes, it changes here, in a PR.

The model is **docs-as-code**, the same approach Vercel, Tailwind, Supabase,
Stripe and Prime Intellect use: the content lives in this repo as Markdown, it
changes in the same pull request as the code it describes, and the site is a
renderer with no content of its own.

---

## 1. Where the content lives

| | |
|---|---|
| Repo | `github.com/prabhu-gopal/bohrin` (public) |
| Branch | `main` — always shippable; never render an unmerged branch |
| Content root | `/docs` |
| Changelog collection | `/docs/releases/*.md` |
| License of the content | Apache-2.0 (same as the code) |

**Do not render** anything outside `/docs`, plus these four repo-root files which
the site *should* surface as pages (see §3): `README.md`, `CHANGELOG.md`,
`CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`.

**Never render** `/parent/` or `CLAUDE.md` — both are git-ignored and not in the
repo, but say it explicitly so nobody wires a path to them: `/parent/` is
internal strategy, `CLAUDE.md` is the maintainer playbook.

### How to get the content into the build

Pick one; option A is simplest if the site build can reach GitHub.

- **A — build-time fetch (recommended).** The site's CI does a sparse checkout of
  `bohrin/main:/docs` (or pulls the raw files) at build time. Always fresh on
  every site deploy. No submodule.
- **B — repository_dispatch trigger.** Add a workflow in *this* repo:
  `on: push` to `main` with `paths: ['docs/**']`, and `on: release`, that fires a
  `repository_dispatch` at the site repo to rebuild. Use this if the site build
  cannot pull from GitHub directly, or if you want the docs repo to "push"
  updates.
- **C — git submodule.** Site repo vendors `bohrin` as a submodule and reads
  `/docs`. Works, but submodule bumps are a chore; only if A and B are
  unavailable.

Whichever you pick: **a merge to `main` touching `docs/**`, and every new
`vX.Y.Z` tag, must trigger a site rebuild.**

---

## 2. Information architecture (the sidebar)

Follows [Diátaxis](https://diataxis.fr/) — the four-mode split (tutorial /
how-to / reference / explanation) that Django and Cloudflare use. Order is the
sidebar order. `slug` is the URL path under `/docs`.

| Section / page | slug | Source | Status |
|---|---|---|---|
| **Overview** | `/docs` | `docs/README.md` (adapt) or new | needs a short landing page |
| **Get started** | | | |
| — Install | `/docs/install` | new | **to write** |
| — Your first audit | `/docs/first-audit` | new (tutorial) | **to write** |
| — Reading a report | `/docs/reading-a-report` | new | **to write** |
| **Guides** | | | |
| — Audit a `verifiers` taskset | `/docs/guides/verifiers-taskset` | new | **to write** |
| — Bound an infinite taskset | `/docs/guides/max-tasks` | new | **to write** |
| — Running without Docker | `/docs/guides/unsafe-local` | new | **to write** |
| — Use the JSON report | `/docs/guides/json-report` | new | **to write** |
| — Reproduce a single finding | `/docs/guides/reproduce-a-finding` | new | **to write** |
| — Add Bohrin to CI | `/docs/guides/ci` | new | **to write** |
| **Concepts** | | | |
| — The audit model | `/docs/concepts/audit-model` | `docs/01_ARCHITECTURE.md` (adapt) | ready to adapt |
| — The Verification Gap | `/docs/concepts/verification-gap` | `docs/02_VERIFICATION_GAP.md` | ready |
| — The two probes | `/docs/concepts/probes` | `docs/03_PROBES.md` | ready |
| — Execution isolation | `/docs/concepts/isolation` | `docs/01` + `docs/05` (extract) | ready to adapt |
| — What's open vs withheld | `/docs/concepts/open-core` | `docs/04_RELEASE.md` | ready |
| — Known limitations | `/docs/concepts/limitations` | `docs/05_ROBUSTNESS.md` | ready |
| **Reference** | | | |
| — CLI: `bohrin audit` | `/docs/reference/cli-audit` | new (from `src/bohrin/cli.py`) | **to write** |
| — CLI: `list-probes`, `explain` | `/docs/reference/cli-other` | new | **to write** |
| — The JSON report schema | `/docs/reference/report-schema` | new (from `report/model.py`) | **to write** |
| — Mutation operators | `/docs/reference/operators` | `docs/03` table (extract) | ready to adapt |
| — Glossary | `/docs/reference/glossary` | new | **to write** |
| **Changelog** | `/changelog` | `docs/releases/*.md` | ready — see §5 |
| **Contributing** | `/docs/contributing` | `CONTRIBUTING.md` | ready |
| **Security** | `/docs/security` | `SECURITY.md` | ready |
| **Code of conduct** | `/docs/code-of-conduct` | `CODE_OF_CONDUCT.md` | ready |

"ready" = the Markdown can be rendered close to as-is. "adapt" = trim the
design-doc framing (these were written to be read before the code existed).
"to write" = content does not exist yet; the repo will add it under `/docs`.

> The five "Concepts" pages sourced from `docs/0X_*.md` are unusually good
> primary material — keep their voice. In particular the framing sentence
> **"Bohrin must never falsely accuse a verifier"** and the rule that **the
> Verification Gap is never shown without its coverage descriptor** are load
> bearing; they appear in the product and must read identically on the site.

---

## 3. Frontmatter contract

Every Markdown file the site renders carries YAML frontmatter. Two shapes.

### 3a. A normal docs page

```yaml
---
title: "Reading a report"          # <h1> and sidebar label and <title>
description: "How to interpret the Verification Gap, findings, and leads."  # meta description + card subtitle
sidebar_label: "Reading a report"  # optional; defaults to title
sidebar_position: 3                # order within its section
---
```

Files sourced from repo-root (`README.md`, `CONTRIBUTING.md`, …) do **not** have
frontmatter. The site supplies title/slug/position for those from a small
mapping table it owns — do not require the repo to add frontmatter to
`README.md`.

### 3b. A release note (`docs/releases/*.md`)

Already specified in [`docs/releases/README.md`](releases/README.md). Recap:

```yaml
---
title: "Bohrin 1.0.1"
version: "1.0.1"          # bare, no leading v
date: "2026-09-05"        # ISO; the string "unreleased" for unreleased.md
tag: "v1.0.1"             # git tag; absent in unreleased.md
breaking: false
summary: >
  One sentence for the changelog index card.
---
```

---

## 4. Markdown features the renderer must support

The content already uses all of these. If the renderer drops one, pages break
silently.

- **GitHub-Flavored Markdown**: tables, task lists, strikethrough, autolinks.
- **Fenced code blocks with a language** (`console`, `python`, `bash`, `toml`,
  `yaml`, `json`, `text`). Syntax highlighting expected. Some blocks use
  `console` with `$` prompts — do not strip the prompt.
- **Inline code** heavily (`bohrin audit`, `--unsafe-local`, `weak_oracle`).
- **Relative links between docs**: `../02_VERIFICATION_GAP.md`,
  `./README.md`, `../../CHANGELOG.md`. The renderer must rewrite `*.md` links to
  site slugs. A link that lands outside `/docs` and the whitelisted repo-root
  files should resolve to the file's GitHub URL, not 404.
- **Heading anchors** — every `##`/`###` gets a stable `id` for deep links.
- **Blockquotes** used as callouts. Optional nicety: promote a blockquote whose
  first line is `**Note**` / `**Warning**` to a styled admonition.
- **Unicode in prose is intentional** — `×`, `→`, `≥`, `·`, box-drawing chars in
  file trees, `█`/`░` in a sample report. Use a font stack that renders them.
- **Long tables and code blocks must scroll inside their own container** — the
  page body never scrolls sideways.
- No MDX/JSX is used today. If you want interactive components later, the repo
  can move to `.mdx`; flag it and we will.

---

## 5. The Changelog page

Built from `docs/releases/*.md`.

- **Include**: every file matching `docs/releases/*.md` **except** `README.md`
  and `_template.md`.
- **Sort**: by frontmatter `date`, newest first. `unreleased.md` (date =
  `"unreleased"`) sorts to the top.
- **`unreleased.md` handling**: render it with an "Unreleased" badge and no date,
  OR show it only on preview/staging builds — your call, but it must never look
  like a shipped version. It has no `tag`.
- **Index view**: one card per release — `title`, `date`, `summary`, and a
  `Breaking` pill when `breaking: true`.
- **Detail view**: the rendered body. The `## Upgrade impact` section should be
  visually prominent (it is the reason the page exists).
- **Per-release permalink**: `/changelog/1.0.1` (from `version`).
- **RSS/Atom feed** at `/changelog.xml` — dependency tools and users subscribe
  to these. One entry per released version, `summary` as the description.
- The GitHub Release for each tag contains the same body; the site and GitHub
  should not disagree.

---

## 6. URLs, stability, redirects

- Slugs are permanent once published. If a page is renamed, the site keeps a
  redirect from the old slug — a docs link in a blog post or a GitHub issue must
  not rot.
- `/changelog` is the canonical changelog path. If you prefer `/docs/changelog`,
  pick one and 301 the other.
- Every docs page has a visible **"Edit this page"** link to
  `github.com/prabhu-gopal/bohrin/edit/main/docs/<path>` (or the repo-root file).
  This is how drive-by fixes happen and it signals the docs are open.
- Every page carries `<title>`, meta `description` (from frontmatter), canonical
  URL, and an Open Graph image. A generated OG card per page (title on brand
  background) is enough.

---

## 7. Search

- Ship search from day one — docs without search frustrate users fast.
- [Algolia DocSearch](https://docsearch.algolia.com/) is free for OSS and is what
  most projects this size use. Apply once the site is live at a stable domain.
- Built-in client-side search (FlexSearch/Pagefind) is a fine interim.

---

## 8. Design system

The docs section lives inside the existing site and inherits its design —
Apple/macOS-clean, green as the primary accent, the same type scale as Home and
Studio. Docs-specific components the team will need:

- **Left sidebar** — the §2 tree, collapsible sections, current-page highlight.
- **Right "On this page"** — the `##`/`###` outline of the current page.
- **Callout / admonition** — note, warning, tip.
- **Code block** — language label, copy button, optional filename header,
  optional line highlighting. A **tabbed** variant for "pip vs uv" style choices.
- **Parameter table** — for the CLI reference (flag, type, default, description).
- **Changelog card** and **Breaking pill** (§5).
- **Version / status badge** — e.g. an "Unreleased" or "Beta" tag on a page.

No login anywhere in Docs — it is fully public and static.

---

## 9. What the repo guarantees to the site

- `main` is protected; nothing lands without a green CI matrix and review, so a
  site build off `main` is never half-written.
- Every user-visible change updates `CHANGELOG.md` **and**
  `docs/releases/unreleased.md` in the same PR (enforced by review, documented in
  `CONTRIBUTING.md`).
- Release notes for shipped versions are immutable — a `1.0.1.md` will never
  change under you, so aggressive caching per-permalink is safe.
- Frontmatter keys in §3 are stable. A new key is added only when the site needs
  it, via a PR that updates this file.
- The `docs/releases/` frontmatter schema and process are documented in
  `docs/releases/README.md`.

## 10. What the site owns (not the repo)

- The route table for repo-root files (`README.md` → `/docs`, etc.).
- Navigation chrome, theme, search config, OG image generation, redirects.
- Analytics.
- The decision on docs **versioning**: recommend **latest-only** now. Add a
  version switcher (v1 / v2) only when there are users on an old major who cannot
  upgrade — realistically at a future `2.0` with a breaking change. Docusaurus
  and Mintlify both support it; it roughly doubles maintenance, so not yet.

---

## 11. First delivery checklist

1. Site build pulls `bohrin/main:/docs` and renders the §2 tree.
2. `/changelog` renders from `docs/releases/` per §5, with the RSS feed.
3. The six "ready" concept pages + Contributing/Security render correctly —
   check tables, code blocks, box-drawing file trees, the `█`/`░` sample report.
4. "Edit this page" links resolve.
5. Search is wired (interim is fine).
6. Rebuild fires on `docs/**` merge and on new tags.

The "to write" pages (Get started, Guides, CLI reference, Glossary) are the
repo's job and will arrive as PRs under `/docs`; the site picks them up
automatically once §1 and §2 are wired.
