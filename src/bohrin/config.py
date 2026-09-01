"""Audit configuration."""

from __future__ import annotations

from dataclasses import dataclass, field

#: Repeats used by the determinism probe. Five is enough to catch a coin-flip verifier
#: with high probability while keeping a 40-task audit to a few hundred calls.
DEFAULT_REPEATS = 5


@dataclass(frozen=True, slots=True)
class ScanConfig:
    """Everything an audit needs that is not the environment itself."""

    #: Maximum reward invocations in flight. Bounded because unbounded parallelism against
    #: a customer's environment is a denial-of-service on the thing we were asked to audit.
    concurrency: int = 8

    #: Seconds allowed for a single reward invocation before it is recorded as an error.
    per_task_timeout: float = 30.0

    #: Cap on tasks probed; None means every task.
    max_tasks: int | None = None

    #: Repeats for the determinism probe.
    repeats: int = DEFAULT_REPEATS

    #: Probe ids to run. Empty means "every discovered probe not in DEFAULT_EXCLUDED".
    only: frozenset[str] = field(default_factory=frozenset)

    #: Run every probe including those held back from a default audit.
    all_probes: bool = False

    #: Permit execution without a verified isolation boundary. Off by default.
    unsafe_local: bool = False
