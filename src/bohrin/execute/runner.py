"""Bounded, fault-tolerant execution of scoring calls.

Every probe routes its reward invocations through here so there is exactly one place that
decides concurrency, timeouts and failure handling.

**Python 3.10 is the supported floor**, and that constrains the implementation. The
ergonomic APIs are both 3.11+:

* ``asyncio.TaskGroup``  → replaced by ``asyncio.gather``
* ``asyncio.timeout()``  → replaced by ``asyncio.wait_for``

Using either would pass on a 3.13 laptop and fail the 3.10 job in CI.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from bohrin.adapters.base import TaskSource
from bohrin.config import ScanConfig
from bohrin.ir.task import Candidate, Task, Verdict


@dataclass(frozen=True, slots=True)
class ScoreOutcome:
    """The result of offering one candidate to one task's verifier."""

    task: Task
    candidate: Candidate
    verdict: Verdict | None = None
    #: Populated instead of ``verdict`` when the call timed out or raised.
    error: str | None = None


async def score_many(
    source: TaskSource,
    work: Sequence[tuple[Task, Candidate]],
    config: ScanConfig,
) -> list[ScoreOutcome]:
    """Score every ``(task, candidate)`` pair with bounded concurrency.

    Failures are captured per item rather than propagated: one task that hangs must not
    abandon the other thirty-nine, and a partial audit with errors recorded is far more
    useful than no audit at all.
    """
    if not work:
        return []

    semaphore = asyncio.Semaphore(max(1, config.concurrency))

    async def _one(task: Task, candidate: Candidate) -> ScoreOutcome:
        async with semaphore:
            try:
                verdict = await asyncio.wait_for(source.score(task, candidate), timeout=config.per_task_timeout)
            except TimeoutError:
                return ScoreOutcome(task, candidate, error=f"timed out after {config.per_task_timeout:g}s")
            except asyncio.CancelledError:
                raise  # cancellation is not an audit finding; let it propagate
            except Exception as exc:
                return ScoreOutcome(task, candidate, error=f"{type(exc).__name__}: {exc}")
            return ScoreOutcome(task, candidate, verdict=verdict)

    gathered = await asyncio.gather(*(_one(t, c) for t, c in work), return_exceptions=True)

    outcomes: list[ScoreOutcome] = []
    for (task, candidate), result in zip(work, gathered, strict=True):
        if isinstance(result, ScoreOutcome):
            outcomes.append(result)
        elif isinstance(result, BaseException):
            outcomes.append(ScoreOutcome(task, candidate, error=f"{type(result).__name__}: {result}"))
    return outcomes


__all__ = ["ScoreOutcome", "score_many"]
