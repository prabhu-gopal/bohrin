"""Adapter for Prime Intellect's `verifiers` v1 tasksets.

The v0 API (`import verifiers as vf`, `vf.load_environment(...)`) has been removed
upstream. v1 is `verifiers.v1`, built on tasksets, harnesses and traces: a Taskset loads
Task objects via `load()`, and a Task carries scoring as `@vf.reward`-decorated async
methods taking a Trace and returning a float.

The consequence that shapes this adapter: **scoring does not need a rollout.** The reward
function is an ordinary async callable, so a candidate is scored by constructing a trace
representing the submission and invoking the reward directly — no agent, no model
inference, no sandboxed rollout for the scoring step.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from bohrin.adapters.base import Adapter, MissingExtraError, TaskSource
from bohrin.ir.task import Candidate, Task, Verdict

if TYPE_CHECKING:
    from bohrin.config import ScanConfig

#: Files that mark a verifiers taskset package on disk.
_TASKSET_FILE = "taskset.py"
_PYPROJECT = "pyproject.toml"


def _available() -> bool:
    try:
        import verifiers.v1  # noqa: F401
    except ImportError:
        return False
    return True


class VerifiersV1Adapter(Adapter):
    """Reads a `verifiers` v1 taskset package."""

    name = "verifiers_v1"

    def detect(self, path: Path) -> float:
        """Detect from files alone, so an uninstalled extra still gives a clear error.

        We deliberately claim the path even when the extra is missing: the layout is
        unambiguous, and "install this extra" is far more useful than "unknown format".
        """
        if not path.is_dir():
            return 0.0
        if any(path.rglob(_TASKSET_FILE)):
            return 0.95 if (path / _PYPROJECT).is_file() else 0.7
        return 0.0

    def load(self, path: Path, config: ScanConfig) -> TaskSource:
        if not _available():
            raise MissingExtraError(
                "this looks like a verifiers taskset; reading it requires: pip install 'bohrin[verifiers]'"
            )
        return _VerifiersSource(path, config)


class _VerifiersSource:
    """A loaded verifiers taskset.

    Not yet implemented: binding to the upstream Taskset/Trace types is the next step and
    needs the package installed to develop against. The adapter is registered now so that
    detection, the missing-extra path, and the CLI wiring are exercised and tested.
    """

    def __init__(self, path: Path, config: ScanConfig) -> None:
        self._path = path
        self._config = config

    def tasks(self) -> Iterator[Task]:
        raise NotImplementedError("verifiers v1 task enumeration is not implemented yet")

    async def score(self, task: Task, candidate: Candidate) -> Verdict:
        raise NotImplementedError("verifiers v1 scoring is not implemented yet")


__all__ = ["VerifiersV1Adapter"]
