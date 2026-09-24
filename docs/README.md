# Bohrin documentation

Pick the page for what you want to do. The pages are kept separate on purpose: a tutorial
teaches, a guide gets a task done, a reference is for looking things up, and an explanation
says why.

| I want to… | Read | Kind |
|---|---|---|
| try it, knowing nothing yet | [tutorial.md](tutorial.md): check your first grader | tutorial |
| understand what Bohrin is and why it works this way | [concepts.md](concepts.md): the idea, the rule, and a glossary | explanation |
| find my way around the code | [ARCHITECTURE.md](../ARCHITECTURE.md): codemap, invariants, boundaries | explanation |
| add a probe | [how-to/add-a-probe.md](how-to/add-a-probe.md) | how-to |
| add or change a weakness class | [how-to/add-a-weakness.md](how-to/add-a-weakness.md) | how-to |
| report a submission wrongly called wrong | [the false-positive form](https://github.com/prabhu-gopal/bohrin/issues/new?template=false_positive.yml) | how-to |
| know the exact rules behind a number | [SPEC.md](SPEC.md) | reference |
| look up a weakness class | [WEAKNESSES.md](WEAKNESSES.md) (generated from `src/bohrin/spec/weaknesses.toml`) | reference |
| see what a reproduction script looks like, and run one | [examples/reproduce_BF-QA8M7NM39K.py](examples/reproduce_BF-QA8M7NM39K.py), described in [SPEC.md](SPEC.md#reproduction-scripts) | reference |
| read or validate a finding record | `src/bohrin/evidence/finding.v1.json`, described in [SPEC.md](SPEC.md#findings) | reference |
| see what a probe tries, as data | `src/bohrin/spec/probes.toml`, described in [SPEC.md](SPEC.md#what-is-tried) | reference |
| contribute | [CONTRIBUTING.md](../CONTRIBUTING.md) | process |
| see what changed | [CHANGELOG.md](../CHANGELOG.md) | reference |
| report a vulnerability | [SECURITY.md](../SECURITY.md) | process |

The API is documented in the docstrings; `help(bohrin.mutate.battery.battery)` and the like work
from Python. Every public type and function has one.
