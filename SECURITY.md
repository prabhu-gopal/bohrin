# Security Policy

## Supported versions

Security fixes land on the latest released version only.

| Version | Supported |
| ------- | --------- |
| 1.1.x   | ✅        |
| 1.0.x   | ❌ — upgrade |
| 0.x     | ❌ — yanked; that line was a different tool, now published as [`adduct`](https://pypi.org/project/adduct/) |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately, either way:

- Email **security@bohrin.com**, or
- Use GitHub's [private vulnerability reporting](https://github.com/prabhu-gopal/bohrin/security/advisories/new)
  on this repository.

Please include, as far as you can:

- What the vulnerability lets an attacker do.
- The steps or input that trigger it — an environment that reproduces it is ideal.
- The `bohrin --version` and Python version you observed it on.

## Response times

| Stage | Target |
| ----- | ------ |
| We acknowledge your report | within **3 business days** |
| We confirm or dispute it, with reasoning | within **10 business days** |
| Fix released, or a public timeline given | within **90 days** of confirmation |

If you do not hear back in 3 business days, please email again — assume the message was
lost rather than ignored.

## Disclosure

We will credit you in the release notes and the advisory unless you prefer otherwise. We
ask that you give us the 90-day window before public disclosure; if a fix is taking longer
than that, we will say so publicly and explain why.

## Scope notes

**Auditing a taskset runs that taskset's own code.** Scoring a candidate invokes the
environment's reward functions, and loading a taskset imports its Python package, which
executes module-level code. That is inherent to what Bohrin does, not a defect: a verifier
cannot be audited without being run. Treat any taskset you did not write as untrusted.

Three properties are load-bearing for the threat model, and a break in any of them is a
security bug worth reporting.

- **Bohrin refuses to execute verifier code with no isolation boundary.** Running without
  one requires the explicit `--unsafe-local` flag. Executing third-party code without
  either a boundary or that flag is a vulnerability.
- **The isolation level used is recorded in every report and never overstated.** A result
  produced in-process must not be presentable as one produced inside a container. A report
  that claims a stronger boundary than the one that actually ran is a vulnerability, and a
  more serious one than a crash, because the whole point of the record is that a third
  party can rely on it.
- **No telemetry.** Bohrin uploads nothing. It makes no network call of its own; a taskset
  may make its own, and that is the taskset's behaviour, not Bohrin's.

### Out of scope

- **Anything `--unsafe-local` enables.** The flag exists to make the risk an explicit,
  documented choice for a taskset you trust. That a hostile taskset can then do hostile
  things is the stated consequence of passing it, not a vulnerability.
- **The `subprocess` isolation level is not a sandbox.** It is described as blast-radius
  containment throughout: process limits bound resource exhaustion, not escape. An escape
  from `subprocess` is expected; an escape from a level documented as stronger is not.

## Verifying what you installed

Releases are published from tagged CI through PyPI Trusted Publishing, with no stored API
token, and carry [PEP 740](https://peps.python.org/pep-0740/) digital attestations. You can
confirm a wheel was built by this repository's workflow from the tag it claims, rather than
trusting that PyPI served it:

```bash
pip install pypi-attestations
pypi-attestations verify pypi bohrin
```

A tool selling verifiable attestation should be able to produce one for itself.
