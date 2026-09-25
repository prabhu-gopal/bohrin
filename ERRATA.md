# Errata

Known mistakes in a **released** part of the standard: the weakness list, the probe battery, the
conformance fixtures and the published formats. Each entry says what was wrong, which releases it
affects, what a result produced with it means now, and where it was fixed. A mistake is recorded
here even when the fix is small, because a score or a conformance claim made with the affected
release may need re-reading. Entries are added, never removed.

Mistakes found and fixed before a release reaches PyPI are in [CHANGELOG.md](CHANGELOG.md), not
here.

## Entry format

```markdown
### E<number> — <one line: what was wrong>

- **Affects:** battery <n> / weakness list v<n> / BCL-<n> version <n> / schema <id>, in releases <versions>
- **Effect on results:** what a score, finding or conformance result produced with it means now
- **Fixed in:** <release>, <pull request>
- **Found by:** how it was found (a dispute, a conformance fixture, an audit)
```

A false accusation that reaches a published finding is also counted in the error rate
(`bohrin.stats.error_rate`, and "Error rates" in [docs/SPEC.md](docs/SPEC.md#error-rates)).

## Entries

None yet.
