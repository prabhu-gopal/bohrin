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

A fixed vulnerability is published as a GitHub security advisory, with a CVE when one is
assigned, and the release that fixes it lists it under **Security** in `CHANGELOG.md` with that
identifier. We will credit you in the release notes and the advisory unless you prefer otherwise. We
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

Every release is built by `.github/workflows/release.yml` from a tag, never on a laptop, and
published through PyPI Trusted Publishing, with no stored API token. Two independent checks tie a
file to that workflow, rather than trusting the server that handed it to you:

- **From PyPI:** each file carries a [PEP 740](https://peps.python.org/pep-0740/) attestation.

  ```console
  $ uvx pypi-attestations verify pypi --repository https://github.com/prabhu-gopal/bohrin \
      pypi:bohrin-X.Y.Z-py3-none-any.whl
  OK: bohrin-X.Y.Z-py3-none-any.whl
  ```

- **From the GitHub release:** each file has a `<file>.sigstore.json` bundle, signed keylessly
  with Sigstore and recorded in its public transparency log.

  ```console
  $ uvx sigstore verify github bohrin-X.Y.Z-py3-none-any.whl \
      --bundle bohrin-X.Y.Z-py3-none-any.whl.sigstore.json \
      --cert-identity https://github.com/prabhu-gopal/bohrin/.github/workflows/release.yml@refs/tags/vX.Y.Z
  ```
