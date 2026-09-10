"""``--timeout`` against reward functions that never yield to the event loop.

Upstream calls a reward function directly on the event-loop thread, and most published
reward functions are plain ``def``. ``asyncio.wait_for`` can only cancel at an ``await``, so
before 1.2 a synchronous grader ran straight past the timeout: measured, a 0.5 s timeout
around a grader sleeping 3 s returned after 3.0 s and was recorded as a successful score.
One grader that never returned would have hung a whole sweep.

Every blocking grader here is *bounded*, so that if the fix regresses a test runs slow and
fails its time assertion rather than hanging CI forever.
"""

from __future__ import annotations

import signal
import time
from types import FrameType

import pytest

from bohrin.adapters.memory import MemorySource
from bohrin.config import ScanConfig
from bohrin.execute.runner import score_many
from bohrin.ir.evidence import HarnessDisruption
from bohrin.ir.task import Candidate, Provenance, Task
from bohrin.probes.weak_oracle import WeakOracleProbe

pytestmark = pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="real-time alarms are POSIX-only")

TIMEOUT = 0.3
#: Generous: the claim is "interrupted near the timeout", not "interrupted at 0.3 s exactly".
#: A regression takes the grader's full 5 s and fails this by a wide margin.
PROMPT_BOUND = 2.5

CONFIG = ScanConfig(concurrency=4, per_task_timeout=TIMEOUT, unsafe_local=True)


def _task(i: int = 0) -> Task:
    return Task(id=str(i), prompt=f"q{i}", reference="42", reward_fns=("r",))


def _cand(payload: str = "x") -> Candidate:
    return Candidate(payload=payload, provenance=Provenance("t", "constant", "d"))


def _sleeps(_task: Task, _payload: str) -> float:
    time.sleep(5)
    return 1.0


def _spins(_task: Task, _payload: str) -> float:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        pass
    return 1.0


def _swallows(_task: Task, _payload: str) -> float:
    """What upstream does around every reward function, and what graders do internally."""
    try:
        time.sleep(5)
    except Exception:
        return 1.0
    return 1.0


@pytest.mark.parametrize("grader", [_sleeps, _spins, _swallows], ids=["sleeps", "spins", "swallows-exceptions"])
async def test_a_synchronous_grader_is_interrupted_at_the_timeout(grader: object) -> None:
    source = MemorySource([_task()], grader)  # type: ignore[arg-type]

    started = time.monotonic()
    [outcome] = await score_many(source, [(_task(), _cand())], CONFIG)
    elapsed = time.monotonic() - started

    assert elapsed < PROMPT_BOUND, f"timeout {TIMEOUT}s was not enforced; took {elapsed:.1f}s"
    assert outcome.verdict is None, "a call that was cut off must not be recorded as a score"
    assert outcome.error is not None and outcome.error.startswith(f"timed out after {TIMEOUT:g}s")


async def test_one_blocked_task_does_not_abandon_the_others() -> None:
    def grade(task: Task, _payload: str) -> float:
        if task.id == "0":
            time.sleep(5)
        return 1.0

    tasks = [_task(i) for i in range(4)]
    outcomes = await score_many(MemorySource(tasks, grade), [(t, _cand()) for t in tasks], CONFIG)

    assert [o.task.id for o in outcomes if o.error] == ["0"]
    assert sorted(o.task.id for o in outcomes if o.verdict is not None) == ["1", "2", "3"]


async def test_back_to_back_stalls_are_each_interrupted() -> None:
    """The case a one-shot alarm missed, measured on 3.13: after one interrupt the next
    stalled grader ran ahead of the heartbeat that should have re-armed it, and ran for its
    full duration. Serial on purpose, so each stall starts the moment the last one ends."""
    tasks = [_task(i) for i in range(3)]
    serial = ScanConfig(concurrency=1, per_task_timeout=TIMEOUT, unsafe_local=True)

    started = time.monotonic()
    outcomes = await score_many(MemorySource(tasks, _sleeps), [(t, _cand()) for t in tasks], serial)
    elapsed = time.monotonic() - started

    assert elapsed < PROMPT_BOUND, f"three {TIMEOUT}s timeouts took {elapsed:.1f}s; one ran to completion"
    assert all(o.error is not None and o.verdict is None for o in outcomes)


async def test_fast_graders_never_trip_the_watchdog() -> None:
    """No false timeouts: the alarm only fires when the loop is genuinely held."""
    tasks = [_task(i) for i in range(50)]
    work = [(t, _cand()) for t in tasks for _ in range(4)]

    outcomes = await score_many(MemorySource(tasks, lambda _t, _p: 1.0), work, CONFIG)

    assert all(o.error is None for o in outcomes)


async def test_the_alarm_is_disarmed_and_the_handler_restored() -> None:
    before = signal.getsignal(signal.SIGALRM)

    await score_many(MemorySource([_task()], _sleeps), [(_task(), _cand())], CONFIG)

    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0), "a live alarm would fire into unrelated code"
    assert signal.getsignal(signal.SIGALRM) == before


async def test_an_existing_owner_of_the_alarm_is_left_alone() -> None:
    """``SIGALRM`` is one process-wide resource. Taking it from code that already uses it
    would break that code silently, so the watchdog stands down instead."""

    def theirs(_signum: int, _frame: FrameType | None) -> None:
        return None

    previous = signal.signal(signal.SIGALRM, theirs)
    try:

        def brief(_task: Task, _payload: str) -> float:
            time.sleep(0.6)
            return 1.0

        started = time.monotonic()
        [outcome] = await score_many(MemorySource([_task()], brief), [(_task(), _cand())], CONFIG)

        assert time.monotonic() - started >= 0.5, "the watchdog armed despite an existing owner"
        assert outcome.verdict is not None
        assert signal.getsignal(signal.SIGALRM) is theirs
    finally:
        signal.signal(signal.SIGALRM, previous)


async def test_a_grader_a_particular_reply_can_hang_is_reported_not_waited_on() -> None:
    """The product consequence. A verifier that one submission can hang is a real
    robustness defect — in training it stalls a rollout worker — and it is now a finding
    instead of an audit that never finishes."""
    tasks = [Task(id=str(i), prompt=f"Echo trap {i}", reference="42", reward_fns=("r",)) for i in range(2)]

    def grade(task: Task, payload: str) -> float:
        if payload == task.prompt:  # the echoed prompt sends this grader into a stall
            time.sleep(5)
        return float(payload.strip() == task.reference)

    started = time.monotonic()
    result = await WeakOracleProbe().run(MemorySource(tasks, grade), CONFIG)

    assert time.monotonic() - started < 2 * PROMPT_BOUND
    disruptions = [f for f in result.findings if isinstance(f, HarnessDisruption)]
    assert disruptions and all(d.operator == "identity_return" for d in disruptions)
