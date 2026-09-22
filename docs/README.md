# Bohrin — design documentation

Bohrin checks the *verifier*: the program that decides whether an RL task was actually
solved. These documents are the open specification — what is tried against a verifier, when a
submission it accepts is provably wrong, and how the result is scored — written to be argued
with.

## Reading order

| Document | Answers |
|---|---|
| [01_ARCHITECTURE.md](01_ARCHITECTURE.md) | How the package is laid out, and the plugin seam |
| [02_VERIFICATION_GAP.md](02_VERIFICATION_GAP.md) | What the number means and how it is computed |
| [03_PROBES.md](03_PROBES.md) | What is tried, what counts as wrong, and why |
| [04_RELEASE.md](04_RELEASE.md) | What this repository holds, and how it is licensed |

## Release notes

[`releases/`](releases/) holds the narrative, user-facing companion to the terse
[`CHANGELOG.md`](../CHANGELOG.md) at the repo root.
[`releases/README.md`](releases/README.md) explains the format and the process for keeping it
current.

## The one rule that governs every design decision here

> **Bohrin must never falsely accuse a verifier.**

A missed defect costs one finding. A false accusation costs the standard its reason to exist —
a check that cries wolf is worth less than no check, because it consumes engineering attention
and destroys the credibility of every other finding.

Everywhere a design choice trades recall against precision, **precision wins**, and the
reasoning is recorded in the relevant document.

## Non-goals

- Bohrin does not train models, and does not provide a reward signal.
- Bohrin does not grade model outputs. That is what a verifier does; Bohrin defines how to
  check the verifier.
