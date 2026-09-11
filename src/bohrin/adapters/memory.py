"""An in-memory task source.

Not registered as an entry point and not a format anyone has on disk: it exists so the
test suite and the fixtures can exercise probes without installing an optional extra or
touching a real environment. Every probe test in this repository runs against it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence

from bohrin.ir.task import Candidate, Task, Verdict

#: A verifier under test: given the task and the submitted payload, return a reward.
Grader = Callable[[Task, str], float]


class MemorySource:
    """A taskset held in memory, with a caller-supplied grader per task."""

    def __init__(
        self,
        tasks: Sequence[Task],
        grader: Grader,
        *,
        pass_at: float = 1.0,
        full_marks: float | None = None,
    ) -> None:
        self._tasks = tuple(tasks)
        self._grader = grader
        self._pass_at = pass_at
        #: Full marks as the grader *declares* them, when a test needs one. A reward above it
        #: is flagged ``scale_exceeded``, exactly as the real adapters flag a rubric paying
        #: past the sum of its weights. ``None`` declares nothing, and nothing is flagged.
        self._full_marks = full_marks
        #: Number of score() calls, so tests can assert on effort as well as outcome.
        self.calls = 0

    def tasks(self) -> Iterator[Task]:
        yield from self._tasks

    async def score(self, task: Task, candidate: Candidate) -> Verdict:
        self.calls += 1
        reward = self._grader(task, candidate.payload)
        return Verdict(
            reward=reward,
            passed=reward >= self._pass_at,
            per_fn={task.reward_fns[0]: reward} if task.reward_fns else {},
            scale_exceeded=self._full_marks is not None and reward > self._full_marks,
        )


__all__ = ["Grader", "MemorySource"]
