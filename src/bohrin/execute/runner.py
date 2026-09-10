"""Bounded, fault-tolerant execution of scoring calls.

Every probe routes its reward invocations through here so there is exactly one place that
decides concurrency, timeouts and failure handling.

``asyncio.gather(..., return_exceptions=True)`` is used rather than ``asyncio.TaskGroup``
on purpose, and not for a version reason — the floor is 3.11, where both exist.
``TaskGroup`` cancels every sibling the moment one child raises: correct for subtasks that
only make sense together, wrong for an audit, where one task whose verifier hangs must not
abandon the other thirty-nine. ``gather`` with ``return_exceptions=True`` gives per-item
failure capture, which is what an audit needs. Timeouts use ``asyncio.wait_for`` for the
same per-item-isolation reason.

**Why the timeout needs more than ``wait_for``.** ``wait_for`` cancels a coroutine, and
cancellation only lands at an ``await``. A reward function written as a plain ``def`` — most
of the published ecosystem, and upstream calls it directly on the event-loop thread — runs
straight through with no ``await`` for the cancellation to land on. Measured before this
module handled it: a 0.5 s timeout around a grader that slept for 3 s returned after 3.0 s,
**recorded as a successful score**. A grader that never returned would have hung the audit,
and every audit queued behind it in a sweep. :func:`_loop_watchdog` closes that.
"""

from __future__ import annotations

import asyncio
import math
import signal
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from types import FrameType

from bohrin.adapters.base import TaskSource
from bohrin.config import ScanConfig
from bohrin.ir.task import Candidate, Task, Verdict


class LoopBlocked(BaseException):
    """Raised into a reward function that held the event loop past the per-call timeout.

    Derived from ``BaseException`` on purpose. Upstream wraps every reward function in
    ``except Exception`` and records a raising one as zero, and reward functions in the wild
    do the same to their own internals: an ``Exception`` raised to stop a hung grader would be
    caught and discarded by exactly the code it was meant to stop. ``KeyboardInterrupt`` is a
    ``BaseException`` for the same reason.
    """

    def __init__(self, timeout: float) -> None:
        super().__init__(f"held the event loop for more than {timeout:g}s")
        self.timeout = timeout


def _can_arm_alarm(timeout: float) -> bool:
    """Whether a real-time alarm can be used here without harming anyone else.

    Signals are POSIX-only and deliverable only to the main thread, and ``SIGALRM`` is one
    process-wide resource: if something else has already claimed it — a handler installed,
    or a timer pending — taking it over would break that code silently. Every one of those
    cases falls back to ``wait_for`` alone, which still bounds reward functions that await.
    """
    if not (hasattr(signal, "setitimer") and hasattr(signal, "SIGALRM")):
        return False
    if threading.current_thread() is not threading.main_thread():
        return False
    if not (math.isfinite(timeout) and timeout > 0):
        return False
    if signal.getsignal(signal.SIGALRM) not in (signal.SIG_DFL, None):
        return False
    return signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


@contextmanager
def _loop_watchdog(loop: asyncio.AbstractEventLoop, timeout: float) -> Iterator[None]:
    """Interrupt synchronous code that holds the event loop for longer than ``timeout``.

    A heartbeat scheduled on the loop re-arms a one-shot real-time alarm a few times a
    second. While the loop is responsive the alarm never expires. When a reward function
    blocks the loop, heartbeats stop, the alarm fires, and the handler raises
    :class:`LoopBlocked` into whatever is executing on the main thread — which, with the loop
    stuck, is the reward function itself. It then propagates to :func:`score_many`, which
    records it against that one call and carries on.

    ``signal.signal`` rather than ``loop.add_signal_handler`` is load-bearing. A loop signal
    handler is a callback the loop runs when it regains control, and the loop regaining
    control is precisely what is not happening.

    What this cannot stop, stated rather than implied: native code that never returns to
    the interpreter, and a reward function that catches ``BaseException`` and keeps going.
    Both still block. Neither is a shape reward functions take in practice.
    """
    if not _can_arm_alarm(timeout):
        yield
        return

    interval = max(0.01, min(0.25, timeout / 4))
    armed = True
    handle: asyncio.TimerHandle | None = None

    def on_alarm(_signum: int, _frame: FrameType | None) -> None:
        # A signal already in flight while the watchdog is torn down must not land in
        # Bohrin's own code, so `armed` is the first thing cleared in `finally`.
        if armed:
            raise LoopBlocked(timeout)

    def beat() -> None:
        nonlocal handle
        # Periodic, not one-shot, and this is measured rather than defensive. A one-shot
        # alarm is spent the moment it fires, and only a heartbeat re-arms it. After an
        # interrupt the loop resumes, but on 3.12+ -- where `wait_for` runs inline instead
        # of spawning a task -- the *next* stalled grader is already ahead of the overdue
        # heartbeat in the ready queue, so it started with no alarm armed and ran its full
        # duration. Two back-to-back stalls took 5.7 s under a 0.3 s timeout. With an
        # interval the alarm re-arms itself, and each heartbeat pushes it back again.
        signal.setitimer(signal.ITIMER_REAL, timeout, timeout)
        handle = loop.call_later(interval, beat)

    previous = signal.signal(signal.SIGALRM, on_alarm)
    try:
        beat()
        yield
    finally:
        armed = False
        signal.setitimer(signal.ITIMER_REAL, 0)
        if handle is not None:
            handle.cancel()
        signal.signal(signal.SIGALRM, previous if previous is not None else signal.SIG_DFL)


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
    timeout = config.per_task_timeout

    async def _one(task: Task, candidate: Candidate) -> ScoreOutcome:
        async with semaphore:
            try:
                verdict = await asyncio.wait_for(source.score(task, candidate), timeout=timeout)
            except TimeoutError:
                return ScoreOutcome(task, candidate, error=f"timed out after {timeout:g}s")
            except LoopBlocked:
                return ScoreOutcome(
                    task,
                    candidate,
                    error=(
                        f"timed out after {timeout:g}s: a synchronous reward function held the "
                        f"event loop and was interrupted"
                    ),
                )
            except asyncio.CancelledError:
                raise  # cancellation is not an audit finding; let it propagate
            except Exception as exc:
                return ScoreOutcome(task, candidate, error=f"{type(exc).__name__}: {exc}")
            return ScoreOutcome(task, candidate, verdict=verdict)

    with _loop_watchdog(asyncio.get_running_loop(), timeout):
        gathered = await asyncio.gather(*(_one(t, c) for t, c in work), return_exceptions=True)

    outcomes: list[ScoreOutcome] = []
    for (task, candidate), result in zip(work, gathered, strict=True):
        if isinstance(result, ScoreOutcome):
            outcomes.append(result)
        elif isinstance(result, BaseException):
            outcomes.append(ScoreOutcome(task, candidate, error=f"{type(result).__name__}: {result}"))
    return outcomes


__all__ = ["LoopBlocked", "ScoreOutcome", "score_many"]
