# How a defect becomes a public record

When Bohrin finds a defect in someone else's grader, environment or benchmark, the maintainer
hears about it first, privately, and has time to act before anything is public. This page is the
policy. The registry record format enforces its timing: a record that breaks it does not validate.

## What happens, in order

1. **The maintainer is told privately**, through the project's published security contact (a
   `SECURITY.md`, GitHub private vulnerability reporting, or the address the project gives). They
   receive:
   - the finding record, with its weakness class and ID;
   - the reproduction script, which runs the exact submission against their own grader and needs
     no Bohrin, no account and no network;
   - the weakness class's fix guidance, and a suggested fix.
2. **The record is published 45 days after that first contact**, or sooner if the defect is fixed
   and the maintainer agrees. It is never published before the maintainer was told.
3. **The record keeps its status up to date:** `reported`, `confirmed`, `fixed`, `disputed` or
   `withdrawn`. A maintainer who disagrees can say so; the record is marked `disputed` and links
   their response. A record found to be wrong is withdrawn, with the date, never deleted: its ID
   is never reused.

## What a record names

The **artefact**: the environment, benchmark, grader or harness, with the versions affected.
**Never a person.** A record describes how a grader behaves, not who wrote it. People who help
(the finder, the maintainer who fixed it) are credited only if they want to be.

## Why 45 days

It is the CERT Coordination Center's default: "Vulnerabilities reported to the CERT/CC will be
disclosed to the public 45 days after the initial report"
([CERT/CC disclosure policy](https://certcc.github.io/certcc_disclosure_policy/)). It sits between
a two-week window, which gives a maintainer too little time to respond, and Google Project Zero's
90 days plus 30 for adoption ([Project Zero policy](https://projectzero.google/vulnerability-disclosure-policy.html)).
The process follows ISO/IEC 29147:2018, the international standard for vulnerability disclosure
([ISO/IEC 29147](https://www.iso.org/standard/72311.html)).

## How the timing is enforced

A registry record carries `disclosure.maintainer_notified`, the date of first private contact.
`bohrin.registry.read_record` refuses a record whose `published` date is before it, or less than
45 days after it, unless `status` is `fixed` and `disclosure.maintainer_agreed_early` is `true`.
The format is in [SPEC.md](SPEC.md#registry-records), and an example record, about the example
grader in this repository, is [examples/BVR-0000-00000.json](examples/BVR-0000-00000.json).

## Defects in Bohrin itself

Those follow [SECURITY.md](../SECURITY.md).
