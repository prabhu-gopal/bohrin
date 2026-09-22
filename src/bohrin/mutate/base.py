"""The mutation operator contract.

An operator turns a task into candidate submissions. Every candidate it emits must carry
the :class:`~bohrin.ir.task.Ground` on which its incorrectness rests, or no ground at all
— in which case the candidate is a lead, never an exploit.

The distinction between text-level and code-level operators is not cosmetic. Inspecting
real tasksets shows most verifiers score a *reply*, not a source file: the reward function
receives a trace and reads its last message. Text-level operators therefore apply to every
task, while code-level operators apply only where the reply is Python that parses.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from bohrin.ir.task import Candidate, Task


class MutationOperator(ABC):
    """Generates candidate submissions for a task."""

    #: Stable identifier, matching the entry-point name.
    id: str = ""

    #: One line explaining what this operator produces and why it is wrong.
    rationale: str = ""

    #: True when the operator needs the reference to parse as Python.
    requires_code: bool = False

    @abstractmethod
    def apply(self, task: Task) -> Iterator[Candidate]:
        """Yield candidates for ``task``, or nothing when the operator does not apply.

        Yielding nothing is the correct behaviour whenever the operator cannot establish
        wrongness for this particular task. Guessing is not an option: a candidate emitted
        without a real ground becomes a false accusation the moment the verifier accepts it.
        """


__all__ = ["MutationOperator"]
