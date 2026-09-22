# What this repository holds

## The standard

This repository is the open standard for checking a grader. Everything in it exists so that a
stranger can read exactly what was tried against a verifier, check why a submission was called
wrong, and recompute the score — without trusting anyone.

| Component | Where | Why it is open |
|---|---|---|
| The battery: what is tried against a grader | `bohrin.mutate.operators`, `bohrin.mutate.battery` | Anyone must be able to read exactly what was tried, and add to it |
| The wrongness rules: when a candidate may be called wrong | `bohrin.ir.task.Ground`, `bohrin.mutate.equivalence`, `bohrin.mutate.battery` | A finding is believed only if its ground can be checked |
| The answer rewritings: when a correct answer is the same answer written another way | `bohrin.relations` | Each carries its own argument, for a reader to accept or reject |
| The scoring rules: the Verification Gap, its coverage, its sides, its weights | `bohrin.scoring` | A metric only its author can compute is not a standard |
| The uncertainty on every rate | `bohrin.scoring.interval` | `2 of 2` and `300 of 300` must never read the same |
| The record types for tasks, candidates, verdicts and findings | `bohrin.ir` | A shared vocabulary is what lets results be compared |

### Commitments

- **Every definition is inspectable.** No check depends on anything not in this repository.
- **The standard grows.** New fixed, model-free operators and certified rewritings are
  welcome, under the burden in [CONTRIBUTING.md](../CONTRIBUTING.md).
- **No telemetry.** Nothing here makes a network call.

## Licence

**Apache 2.0**, decided once. A source-available licence would undermine the transparency a
standard depends on, and a standard that cannot be freely implemented is not one.

A permissive licence lets anyone fork and relicense; the one thing a fork cannot do is use the
name.

## Contributions

DCO, not a CLA. A CLA signals exactly the intent that makes engineers distrust a project, and
contributors keep the copyright to what they write.

The contribution surface is operators and relations. The metric definition, its weights and
the scoring rules change only on measured evidence, because their stability is what makes the
number citable.

## Findings about other people's graders

The standard is used to examine graders other people maintain, and those maintainers are the
people it exists to serve. Publishing defect data about their work without notice would be
both discourteous and self-defeating.

- Maintainers are notified privately, with reproduction detail, and given a defined window to
  respond before publication.
- Published findings characterise the defect class and its magnitude.
- Work under active remediation is reported as such, not as an unqualified failure.
- Aggregate reporting describes the state of the ecosystem, **not** the competence of
  individual maintainers, and says so explicitly.

## Authorisation

The battery constructs submissions a weak grader will pay for. The same artefact that lets a
maintainer repair a grader lets a third party exploit one. The security industry's settled
norm is not to withhold the category but to bind use to authorisation from the system owner,
and this project adopts it: use the battery against graders you own or are authorised to
assess.
