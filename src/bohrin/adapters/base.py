"""The adapter contract.

An adapter is the only code that touches a format-specific environment. It turns any
taskset into :class:`~bohrin.ir.task.Task` objects and exposes one way to score a
candidate. Adding a format is one class and one entry point; probes never change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from bohrin.ir.task import Candidate, Task, Verdict

if TYPE_CHECKING:
    from bohrin.config import ScanConfig


class MissingExtraError(ImportError):
    """An optional extra is not installed, and the message names the pip command.

    Distinct from a bare ``ImportError`` so the CLI can print it as a fixable input rather
    than a traceback, without also swallowing a genuinely broken install. It subclasses
    ``ImportError`` so ``except ImportError`` callers keep working.
    """


class UnknownFormatError(Exception):
    """No adapter recognised the path."""


@runtime_checkable
class TaskSource(Protocol):
    """A loaded taskset: enumerate tasks, and score candidates against their verifier."""

    def tasks(self) -> Iterator[Task]:
        """Yield every task in the taskset."""
        ...

    async def score(self, task: Task, candidate: Candidate) -> Verdict:
        """Submit ``candidate`` to ``task``'s verifier and return what it said.

        This is the only method that executes the environment's own code, which keeps the
        isolation boundary in one place.
        """
        ...


class Adapter(ABC):
    """Binds one environment format to the canonical task representation."""

    #: Stable identifier, matching the entry-point name.
    name: str = ""

    @abstractmethod
    def detect(self, path: Path) -> float:
        """Confidence in ``[0.0, 1.0]`` that this adapter can read ``path``.

        Detection reads files only and never imports the environment, so an uninstalled
        optional dependency still produces a clear "install this extra" message rather
        than an unhelpful "unknown format".
        """

    @abstractmethod
    def load(self, path: Path, config: ScanConfig) -> TaskSource:
        """Open ``path``. Raises :class:`MissingExtraError` if a required extra is absent."""


__all__ = ["Adapter", "MissingExtraError", "TaskSource", "UnknownFormatError"]
