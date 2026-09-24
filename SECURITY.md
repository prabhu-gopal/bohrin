# Security Policy

## Supported versions

Security fixes land on the latest released version only.

| Version | Supported |
| ------- | --------- |
| 0.3.x   | ✅        |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately, either way:

- Email **security@bohrin.com**, or
- Use GitHub's [private vulnerability reporting](https://github.com/prabhu-gopal/bohrin/security/advisories/new)
  on this repository.

Please include, as far as you can:

- What the vulnerability lets an attacker do.
- The steps or input that trigger it — an environment that reproduces it is ideal.
- The Bohrin version (`python -c 'import bohrin; print(bohrin.__version__)'`) and Python version you observed it on.

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

**Bohrin executes no grader code, and no code taken from a task.** It builds candidate
submissions from a task's reference solution by parsing it with LibCST. To decide whether a
candidate is the reference written another way, it compiles both with `compile` and compares
the bytecode, or parses a bare value as JSON or a Python literal. It never runs any of them,
and it has no module that opens a network connection. The one process it starts is `git`, for
`bohrin verify`, and only for read-only plumbing on committed history, with the programs a
repository can name (fsmonitor, external diff, hooks) switched off. It never asks git to diff
the working tree, because that runs a repository's filters; it reads working-tree files itself,
without following symlinks. Tests check all of this, including in a deliberately booby-trapped
repository.
The data it reads is its own: the weakness list, the probe manifests and the finding schema that
ship inside the package. Anything that makes Bohrin execute text taken from a task is a
vulnerability.

- **No telemetry.** Bohrin uploads nothing and makes no network call of its own.
- **Third-party plugins are code you chose to install.** Operators and relations register
  through public entry points, and a plugin runs with the permissions of the process that
  loads it. That a malicious plugin can do malicious things is not a vulnerability in Bohrin.

## Verifying what you installed

Releases are published from tagged CI through PyPI Trusted Publishing, with no stored API
token, and carry [PEP 740](https://peps.python.org/pep-0740/) digital attestations. You can
confirm a wheel was built by this repository's workflow from the tag it claims, rather than
trusting that PyPI served it:

```bash
pip install pypi-attestations
pypi-attestations verify pypi bohrin
```

