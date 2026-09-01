# Security Policy

## Supported versions

Bohrin is pre-1.0. Security fixes land on the latest released version only.

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅        |
| < 0.1   | ❌        |

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

Two properties are load-bearing for bohrin's threat model, and a break in either is a
security bug worth reporting:

- **Bohrin makes no network calls except an explicit Hugging Face Hub fetch**, which
  happens only when you pass a `owner/name` repo id. There is no telemetry, and no scanned
  data is ever uploaded.
- **Bohrin never unpickles a checkpoint.** `--policy` reads safetensors, ONNX, and JSON
  config only. If you find an input that causes arbitrary code execution — through a
  checkpoint, an environment file, or a `bohrin.yaml` — that is a vulnerability.
