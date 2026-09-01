"""Adapter for Prime Intellect's `verifiers` v1 tasksets.

The v0 API (`import verifiers as vf`, `vf.load_environment(...)`) has been removed
upstream. v1 is `verifiers.v1`, built on tasksets, tasks and traces.

Everything below was established by introspecting the installed package rather than from
documentation, because three of the load-bearing details are not written down anywhere and
getting any of them wrong produces confidently incorrect audits.

**How scoring actually works.** `Task.score(trace, runtime=None)` returns ``None`` — it
*mutates* the trace, recording each reward under `trace.rewards`. `Trace.reward` is then
the sum of the weighted rewards that ran. So a candidate is scored by building a trace
that represents the submission and invoking `score` directly: no agent, no model
inference, no rollout.

**The trap that shapes this whole module.** When `runtime is None`, `Task.score` filters
out every reward function whose signature has a non-defaulted `runtime` parameter, *before
seeding*, so those rewards never appear in `trace.rewards` at all. `Trace.reward` sums only
what ran. A task with one offline reward and one container-backed reward would therefore
award full offline marks to a submission that does nothing — and Bohrin would report a
false exploit against a verifier that is in fact correct.

Such tasks are refused rather than half-scored. See :func:`_requires_runtime`.
"""

from __future__ import annotations

import inspect
import tomllib
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bohrin.adapters.base import Adapter, MissingExtraError, TaskSource
from bohrin.ir.task import Candidate, Task, Verdict

if TYPE_CHECKING:
    from bohrin.config import ScanConfig

#: Files that mark a verifiers taskset package on disk.
_TASKSET_FILE = "taskset.py"
_PYPROJECT = "pyproject.toml"

#: Fields a taskset commonly uses for a known-good answer. `TaskData` standardises `prompt`
#: and `description` but not the reference, so this is a documented best effort: when none
#: is present the task is probed with structural operators only, which is honest and still
#: useful — it is never guessed at.
_REFERENCE_FIELDS = ("answer", "solution", "reference", "expected", "target", "ground_truth")


def _available() -> bool:
    try:
        import verifiers.v1  # noqa: F401
    except ImportError:
        return False
    return True


def _requires_runtime(fn: Callable[..., Any]) -> bool:
    """Whether ``fn`` needs a runtime, by the same rule upstream applies.

    Mirrors the check inside ``Task.score``: a ``runtime`` parameter with no default. A
    defaulted one can still be called offline with ``None``.

    This is deliberately a re-implementation of a private upstream behaviour, and it is
    pinned by a test so that an upstream change surfaces as a failure rather than as
    silently wrong audits.
    """
    try:
        param = inspect.signature(fn).parameters.get("runtime")
    except (TypeError, ValueError):  # builtins and C callables have no signature
        return False
    return param is not None and param.default is inspect.Parameter.empty


def _first_reference(data: Any) -> str | None:
    """A known-good answer from the task data, if the taskset exposes one under a name we
    recognise. Returns None rather than guessing."""
    for field in _REFERENCE_FIELDS:
        value = getattr(data, field, None)
        if value is None or isinstance(value, bool):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def reference_renderings(answer: str) -> list[str]:
    """Plausible ways a correct answer might be *submitted*, most literal first.

    The field a taskset stores holds the answer (``70``); the reward function may require a
    particular presentation of it (``\\boxed{70}``). Those are not the same string, and
    assuming they were made the baseline fail on the first real environment tried — aime25
    scores with ``verify_boxed_math_answer``, so the bare answer never passes.

    The baseline therefore searches: whichever rendering the verifier actually accepts is
    the known-good submission. If none is accepted, the task is unmeasurable and is reported
    as such rather than probed against a reference the verifier itself rejects.
    """
    # The unmodified value comes first and is never stripped: a verifier doing an exact
    # string comparison rejects a reference whose trailing newline we removed, which would
    # fail the baseline on a task that is in fact perfectly scoreable.
    bare = answer.strip()
    return [
        answer,
        *([bare] if bare != answer else []),
        f"\\boxed{{{answer}}}",
        f"$\\boxed{{{answer}}}$",
        f"The answer is {answer}.",
        f"The answer is \\boxed{{{answer}}}.",
        f"**{answer}**",
        f"\\boxed{{\\text{{{answer}}}}}",
    ]


def _taskset_id(path: Path) -> str | None:
    """The taskset id for a package directory.

    Upstream resolves an id (`owner/name`, or a bare `name`) to an *installed* module, so
    the id is the distribution name from the package's own pyproject.
    """
    for candidate in (path / _PYPROJECT, *(p / _PYPROJECT for p in sorted(path.glob("*")) if p.is_dir())):
        if not candidate.is_file():
            continue
        try:
            meta = tomllib.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        name = meta.get("project", {}).get("name")
        if isinstance(name, str) and name:
            return name
    return None


class VerifiersV1Adapter(Adapter):
    """Reads a `verifiers` v1 taskset."""

    name = "verifiers_v1"

    def detect(self, path: Path) -> float:
        """Detect from files alone, so an uninstalled extra still gives a clear error.

        We deliberately claim the path even when the extra is missing: the layout is
        unambiguous, and "install this extra" is far more useful than "unknown format".
        """
        if not path.is_dir():
            return 0.0
        if any(path.rglob(_TASKSET_FILE)):
            return 0.95 if _taskset_id(path) else 0.7
        return 0.0

    def load(self, path: Path, config: ScanConfig) -> TaskSource:
        if not _available():
            raise MissingExtraError(
                "this looks like a verifiers taskset; reading it requires: pip install 'bohrin[verifiers]'"
            )
        taskset_id = _taskset_id(path)
        if taskset_id is None:
            raise MissingExtraError(
                f"found a {_TASKSET_FILE} under {str(path)!r} but no pyproject.toml naming the package. "
                f"A verifiers taskset is an installed Python package; install it first, e.g. "
                f"pip install -e {str(path)!r}"
            )
        return _VerifiersSource(taskset_id, config)


class _VerifiersSource:
    """A loaded verifiers taskset, exposed through Bohrin's task interface."""

    def __init__(self, taskset_id: str, config: ScanConfig) -> None:
        import verifiers.v1 as vf

        self._vf = vf
        self._id = taskset_id
        self._config = config
        try:
            # A taskset may specialise TasksetConfig with its own fields (dataset subsets,
            # revisions, splits). Constructing the base class instead leaves those missing
            # and load() dies with AttributeError, so resolve the taskset's own type.
            config_type = vf.taskset_config_type(taskset_id)
            taskset = vf.load_taskset(config_type(id=taskset_id))
        except ModuleNotFoundError as exc:
            raise MissingExtraError(
                f"taskset {taskset_id!r} is not installed. A verifiers taskset is an installed "
                f"Python package — install it first (pip install -e <path>) and re-run. ({exc})"
            ) from exc
        if config.max_tasks is not None:
            taskset = taskset.head(config.max_tasks)
        self._taskset = taskset
        #: Bohrin task id -> the upstream task object, populated by tasks().
        self._by_id: dict[str, Any] = {}

    def tasks(self) -> Iterator[Task]:
        for index, vf_task in enumerate(self._taskset.load()):
            data = vf_task.data
            reward_fns = tuple(fn.__name__ for fn in vf_task.hooks("reward"))
            needs_runtime = tuple(fn.__name__ for fn in vf_task.hooks("reward") if _requires_runtime(fn))

            task_id = str(getattr(data, "name", None) or getattr(data, "idx", None) or index)
            self._by_id[task_id] = vf_task

            yield Task(
                id=task_id,
                prompt=str(getattr(data, "prompt", "") or getattr(data, "description", "") or ""),
                reference=_first_reference(data),
                reward_fns=reward_fns,
                metadata={
                    "taskset": self._id,
                    "task_type": type(vf_task).__name__,
                    "key": getattr(vf_task, "key", ""),
                    # Recorded so the probe and the report can say why a task was refused
                    # rather than silently producing a number from a partial rubric.
                    "requires_runtime": needs_runtime,
                    "offline_scoreable": not needs_runtime,
                },
            )

    def _trace_for(self, vf_task: Any, payload: str) -> Any:
        """A trace whose last model reply is ``payload``.

        ``sampled=True`` is load-bearing: ``Trace.assistant_messages`` keeps only sampled
        assistant nodes, so a node without it is invisible and ``last_reply`` comes back
        empty — every candidate would then be scored as an empty submission.
        """
        vf = self._vf
        return vf.Trace(
            task=vf.TraceTask(type=type(vf_task).__name__, data=vf_task.data),
            agent=vf.AgentInfo(config=vf.AgentConfig()),
            nodes=[vf.MessageNode(message=vf.AssistantMessage(content=payload), sampled=True)],
        )

    async def score(self, task: Task, candidate: Candidate) -> Verdict:
        vf_task = self._by_id.get(task.id)
        if vf_task is None:
            raise KeyError(f"task {task.id!r} was not produced by this source")

        if task.metadata.get("requires_runtime"):
            names = ", ".join(task.metadata["requires_runtime"])
            raise RuntimeError(
                f"task {task.id!r} has reward function(s) requiring a runtime ({names}). "
                f"Scoring offline would skip them and award full marks on a partial rubric, "
                f"which manufactures false exploits. Run with a runtime, or exclude this task."
            )

        trace = self._trace_for(vf_task, candidate.payload)
        await vf_task.score(trace)

        per_fn = {name: reward.score for name, reward in trace.rewards.items() if reward is not None}
        skipped = [name for name, reward in trace.rewards.items() if reward is None]
        total = float(trace.reward)

        # Full marks means the verifier rewarded this exactly as it would a correct
        # submission. Anything less is a partial score, not acceptance.
        attainable = sum(r.weight for r in trace.rewards.values() if r is not None)

        return Verdict(
            reward=total,
            passed=bool(attainable) and total >= attainable,
            per_fn=per_fn,
            raw={
                "attainable": attainable,
                "skipped_rewards": skipped,
                "declared_rewards": list(task.reward_fns),
            },
        )


__all__ = ["VerifiersV1Adapter", "reference_renderings"]
