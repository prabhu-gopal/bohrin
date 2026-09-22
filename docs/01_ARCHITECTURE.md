# Architecture

## Layout

`src/` layout, because it forces tests to import the installed package rather than the
working directory.

```
bohrin/
├── src/bohrin/
│   ├── __init__.py
│   ├── version.py            # __version__
│   ├── _plugins.py           # entry-point discovery — no privileged path
│   │
│   ├── ir/                   # the canonical types
│   │   ├── task.py           # Task, Candidate, Ground, Provenance, Verdict
│   │   ├── evidence.py       # the finding records
│   │   └── result.py         # ProbeResult, ProbeStatus
│   │
│   ├── mutate/               # what is tried, and what may be called wrong
│   │   ├── base.py           # MutationOperator
│   │   ├── operators.py      # the nine built-in operators
│   │   ├── equivalence.py    # when two payloads are really different
│   │   └── battery.py        # every candidate for a task, with the rules applied
│   │
│   ├── relations/            # certified meaning-preserving answer rewritings
│   │   ├── base.py           # Relation
│   │   └── builtin.py        # the seventeen built-ins
│   │
│   └── scoring/
│       ├── gap.py            # Verification Gap, coverage, sides, published weights
│       └── interval.py       # the Wilson interval on every rate
│
├── tests/                    # mirrors src/bohrin/
├── docs/
└── pyproject.toml
```

## The core types

Every definition is written against the types in `ir/` and **never** against a specific
environment format, which is what keeps the definitions portable.

```python
@dataclass(frozen=True, slots=True)
class Task:
    """One unit of work with a verifier attached."""

    id: str
    prompt: str
    reference: str | None = None  # known-good answer text, when the taskset provides one
    reward_fns: tuple[str, ...] = ()  # named criteria the verifier scores
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A constructed submission, with a claim about its correctness."""

    payload: str
    provenance: Provenance  # which operator produced it, from what
    ground: Ground | None = None  # how wrongness was established, or None if it was not

    @property
    def known_wrong(self) -> bool:  # True iff ground is not None
        return self.ground is not None


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the verifier said."""

    reward: float
    passed: bool
    per_fn: Mapping[str, float] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)
```

`ground` is the load-bearing field. A `Candidate` carries one only when its incorrectness has
been established independently of the verifier under audit (`Ground.STRUCTURAL` /
`DIFFERENTIAL` / `INVARIANT`) — see [03_PROBES.md](03_PROBES.md#establishing-wrongness). An
exploit is `known_wrong and passed`, and nothing else counts.

## The battery

`mutate.battery.battery(task)` asks every registered operator for candidates and applies the
rules every operator is held to, first-party and third-party alike:

- duplicate payloads are tried once;
- a grounded candidate that *is* the declared answer — as an answer under the equivalence
  ladder, or as a program under Trivial Compiler Equivalence — is suppressed and counted;
- grounds the declared answer cannot support are withdrawn: all of them where the answer is a
  refusal, and the answer-dependent ones where the "answer" is a JSON object of grader state.

Each rule can only remove a ground. None can create one.

## The plugin seam

Operators and relations are discovered through entry points. First-party and third-party
plugins use the identical mechanism; there is no privileged path and no licence check anywhere
in this repository.

```toml
[project.entry-points."bohrin.mutators"]
empty_body = "bohrin.mutate.operators:EmptyBody"

[project.entry-points."bohrin.relations"]
verbatim = "bohrin.relations.builtin:Verbatim"
```

The group names `bohrin.mutators` and `bohrin.relations` are **public API**: renaming either
breaks every third-party plugin at once. A plugin that raises on load is skipped with a
warning — one bad plugin must never take down discovery. Relation order is fixed by the
catalogue, not by the entry-point table, so a third-party relation is appended and can never
reorder an existing search.

## Mutation via LibCST, not `ast`

The code-level operators rewrite source. The stdlib `ast` module is lossy — it discards
comments, whitespace and formatting, so a round trip reformats the whole file. **LibCST** is a
concrete syntax tree: it preserves formatting and reprints exactly.

That matters for a reason beyond aesthetics. **The mutant is the evidence.** A reader must be
able to diff it against the reference and see a one-line change; an `ast` round trip buries
the actual mutation in incidental churn.

## Supported Python

3.11 to 3.13, each tested on Linux and macOS in CI.
