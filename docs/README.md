# Bohrin — design documentation

Bohrin audits the *verifier*: the program that decides whether an RL task was
actually solved. It reports one number, the **Verification Gap**, and the
evidence behind it.

These documents are the design record for the open-source core. They are written
to be read before the code exists, and to be argued with.

## Reading order

| Document | Answers |
|---|---|
| [01_ARCHITECTURE.md](01_ARCHITECTURE.md) | How the codebase is laid out, and where the open/closed seam falls |
| [02_VERIFICATION_GAP.md](02_VERIFICATION_GAP.md) | What the number means and how it is computed |
| [03_PROBES.md](03_PROBES.md) | Detailed design of the two probes shipping in the open core |
| [04_RELEASE.md](04_RELEASE.md) | What is released, what is withheld, and what 1.0.0 shipped |
| [05_ROBUSTNESS.md](05_ROBUSTNESS.md) | Known weaknesses, ranked, with the evidence behind each |

## The one rule that governs every design decision here

> **Bohrin must never falsely accuse a verifier.**

A missed exploit costs a customer one finding. A false accusation costs the
product its reason to exist — an auditing tool that cries wolf is worth less
than no auditing tool, because it consumes engineering attention and destroys
the credibility of every other finding in the report.

Everywhere a design choice trades recall against precision in this codebase,
**precision wins**, and the reasoning is recorded in the relevant document.

## Non-goals

- Bohrin does not train models, and does not provide a reward signal.
- Bohrin does not host or execute environments. It runs on the caller's
  infrastructure and provisions no compute.
- Bohrin does not grade model outputs. That is what a verifier does; Bohrin
  grades the verifier.
