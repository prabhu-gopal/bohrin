# Architecture

## Layout

`src/` layout, because it forces tests to import the installed package rather
than the working directory — the same reason the previous codebase used it.

```
bohrin/
├── src/bohrin/
│   ├── __init__.py
│   ├── version.py            # __version__ + REPORT_SCHEMA_VERSION
│   ├── cli.py                # argparse; audit / list-probes / explain
│   ├── _plugins.py           # entry-point discovery — no privileged path
│   ├── config.py             # ScanConfig; bohrin.yaml
│   │
│   ├── ir/                   # what a probe sees
│   │   ├── task.py           # Task, Candidate, Verdict
│   │   └── evidence.py       # Exploit, Evidence
│   │
│   ├── adapters/             # bind to an environment format
│   │   ├── base.py           # Adapter ABC, MissingExtraError
│   │   ├── registry.py       # detect() → best adapter
│   │   └── verifiers_v1.py   # the one that matters at launch
│   │
│   ├── probes/
│   │   ├── base.py           # Probe ABC, ProbeResult
│   │   ├── registry.py       # discovery + DEFAULT_EXCLUDED
│   │   ├── weak_oracle.py    # open
│   │   └── determinism.py    # open
│   │
│   ├── mutate/               # candidate generation (harness only)
│   │   ├── base.py           # Mutation, MutationOperator
│   │   └── operators.py      # the free baseline set
│   │
│   ├── execute/
│   │   ├── isolation.py      # detect sandbox properties; refuse if absent
│   │   └── runner.py         # submit Candidate → Verdict
│   │
│   ├── scoring/
│   │   └── gap.py            # Verification Gap + coverage
│   │
│   └── report/
│       ├── model.py          # Report — the versioned contract
│       ├── tty.py │ html.py │ json_out.py
│
├── tests/                    # mirrors src/bohrin/
├── docs/
└── pyproject.toml
```

## The core types

Everything a probe touches is defined in `ir/`. Probes are written against these
and **never** against a specific environment format — that is what makes the
adapter layer replaceable and the probe set portable.

```python
@dataclass(frozen=True, slots=True)
class Task:
    """One unit of work with a verifier attached."""
    id: str
    prompt: str
    reference: Solution | None    # known-good, when the taskset provides one
    reward_fns: tuple[str, ...]   # named criteria the verifier scores
    metadata: Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class Candidate:
    """A submission constructed by Bohrin, with a claim about its correctness."""
    payload: str
    provenance: Provenance        # which operator produced it, from what
    known_wrong: bool             # only True when independently established

@dataclass(frozen=True, slots=True)
class Verdict:
    """What the verifier said."""
    reward: float
    per_fn: Mapping[str, float]
    passed: bool
    raw: Mapping[str, Any]
```

`known_wrong` is the load-bearing field. A `Candidate` may only set it when
incorrectness has been established independently of the verifier under audit
— see [03_PROBES.md](03_PROBES.md#establishing-wrongness). An exploit is
`known_wrong and passed`, and nothing else counts.

## The plugin seam

Probes are discovered through entry points. First-party and third-party probes
use the identical mechanism; there is no privileged path and no licence check
anywhere in this repository.

```toml
# public — this repo
[project.entry-points."bohrin.probes"]
weak_oracle = "bohrin.probes.weak_oracle:WeakOracleProbe"
determinism = "bohrin.probes.determinism:DeterminismProbe"
```

```toml
# proprietary — separate repo, never referenced from here
[project.entry-points."bohrin.probes"]
isomorphic = "bohrin_attack.probes.isomorphic:IsomorphicProbe"
```

Consequences, all deliberate:

- This repository is complete and useful with nothing proprietary installed.
- A probe moves from closed to open by relocating one file — and never the
  reverse.
- The entry-point group name `bohrin.probes` is **public API**. Renaming it
  breaks every paying customer and every third-party plugin at once.

The same mechanism carries `bohrin.adapters` and `bohrin.mutators`.

## Adapters: `verifiers` v1

The target is Prime Intellect's `verifiers`, because environments there are
installable Python modules, which makes a large installed base addressable
through one adapter.

**The v0 API (`import verifiers as vf`, `vf.load_environment()`) has been
removed.** v1 is `import verifiers.v1 as vf`, built on tasksets, harnesses and
traces:

- a **Taskset** loads **Task** objects via `load()`
- a **Task** carries scoring as `@vf.reward`-decorated async methods
- each reward takes a **`Trace`** (the message graph) and returns a `float`
- **runtimes** are `subprocess`, `docker`, or a remote sandbox

The consequence that shapes the whole MVP:

> **Bohrin can score a candidate without running a rollout.** The reward
> function is an ordinary async callable over a `Trace`. Bohrin constructs a
> synthetic `Trace` representing a submission and invokes the reward directly.

No agent, no model inference, no sandbox for the *scoring* step — deterministic,
fast, and cheap. Model inference is needed only where candidate *generation*
requires it, and the free baseline operators (see 03) are deterministic and need
none. A first audit is therefore seconds, not minutes, which is what makes the
"under 15 minutes to first value" target reachable.

Adapter surface:

```python
class Adapter(ABC):
    name: str
    def detect(self, path: Path) -> float: ...          # 0.0–1.0 confidence
    def load(self, path: Path, cfg: ScanConfig) -> TaskSource: ...

class TaskSource(Protocol):
    def tasks(self) -> Iterator[Task]: ...
    async def score(self, task: Task, cand: Candidate) -> Verdict: ...
```

`score()` is the only method that touches the environment's own code, which
keeps the isolation boundary in one place.

## Execution isolation

Bohrin submits candidates it generated to code the customer wrote. Even with
deterministic operators, the *environment's* reward function executes — so the
untrusted-code boundary is real from day one.

`execute/isolation.py` does not provide a sandbox. It **detects** what the
caller has and refuses to proceed when required properties are absent:

| Property | Why |
|---|---|
| No ambient credentials | A probe must never reach cloud/registry/repo secrets |
| Default-deny egress | Network only where the task genuinely requires it |
| Hard resource ceilings | Exploit search is unbounded by nature; cap it |
| Ephemeral filesystem | One probe must not contaminate the next |
| Per-execution audit record | It is both the report evidence and the certificate basis |

Default runtime is `docker`; `subprocess` requires `--unsafe-local` and prints a
warning, because the upstream docs themselves note subprocess rollouts can have
cross-process side effects. A sandbox escape caused by Bohrin on customer
infrastructure would end a company whose product is trust — this is a product
requirement, not an implementation detail.

## Report contract

`report/model.py` defines `Report`, serialised by `--json`. It carries
`schema_version`, frozen and versioned independently of the package, exactly as
the previous codebase did. Consumers depend on it; it changes on a documented
schedule or not at all.

Every finding carries its **reproduction command**. The report leads with
exploit code, not charts — a nine-line file that scores 100% on the customer's
own task is the argument.
