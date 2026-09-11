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

**The read path is `iter(taskset)`, not `taskset.load()`.** `load` is the subclass hook
that builds tasks; iterating the taskset is what applies the config-layer system prompt
and any `head`/`shuffle` view on top. Calling `load` directly silently discards both —
``--max-tasks`` stops bounding anything, so an infinite taskset hangs the audit forever,
and a taskset configured with a system prompt gets audited without it, which is a
different task from the one that actually runs.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bohrin.adapters._package import distribution_name
from bohrin.adapters.base import Adapter, MissingExtraError, TasksetLoadError, TaskSource
from bohrin.ir.task import Candidate, Task, Verdict
from bohrin.relations import renderings as relation_renderings

if TYPE_CHECKING:
    from bohrin.config import ScanConfig

#: The file that marks a verifiers taskset package on disk.
_TASKSET_FILE = "taskset.py"

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


#: Task-data fields that are never a reference answer, whatever a reward function does
#: with them. `TaskData` standardises these, and a reward reading `self.data.prompt` is
#: reading the question, not the answer -- submitting the prompt as a known-good baseline
#: would be nonsense, and worse, would make `constant_return` compare against it.
_NEVER_A_REFERENCE = frozenset(
    {
        "idx",
        "name",
        "description",
        "prompt",
        "system_prompt",
        "image",
        "workdir",
        "network_allow",
        "network_block",
        "artifacts",
        "timeout",
        "resources",
        "info",
        "metadata",
    }
)


class _DataFieldReader(ast.NodeVisitor):
    """Collects the ``self.data.<field>`` names a reward function actually reads.

    Parsed, not pattern-matched. A regular expression over the source is the obvious
    implementation and it is wrong here in a way that matters: it matches inside comments
    and docstrings. A reward whose docstring says *"compares against self.data.answer"*
    would contribute a phantom field, and because :func:`_reference_by_contract` requires
    exactly one candidate, one phantom silently suppresses a real discovery. The AST sees
    only what the code does.

    Two access forms are recognised, because both appear in real tasksets:
    ``self.data.word`` and ``getattr(self.data, "word")``.
    """

    def __init__(self) -> None:
        self.fields: set[str] = set()

    @staticmethod
    def _is_self_data(node: ast.expr) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "data"
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        )

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._is_self_data(node.value):
            self.fields.add(node.attr)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and node.args
            and self._is_self_data(node.args[0])
            and len(node.args) > 1
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            self.fields.add(node.args[1].value)
        self.generic_visit(node)


def _reference_by_contract(vf_task: Any) -> str | None:
    """The answer a reward function actually reads, when the field is not one we guess.

    Name-based lookup asks "is the answer stored under one of six names we thought of?".
    That is a guess about naming convention, and it fails on tasksets that named the field
    after their domain -- `scratchpad` stores its answer as ``word`` and grades with
    ``self.data.word in answer``, so all its tasks were probed with no reference at all.

    This asks the better question: **which task-data field does the verifier itself
    consult?** That is the contract, and it is readable from the reward function's own
    source. A field the grader compares against is the grader's notion of the right answer,
    by definition.

    Deliberately conservative, because a wrong reference is worse than none -- it becomes
    the baseline, and `constant_return` claims a differential ground against it:

    * standard `TaskData` fields are excluded outright (:data:`_NEVER_A_REFERENCE`);
    * **exactly one** remaining candidate must be found. Two fields consulted by the reward
      leave no principled way to choose, and picking either would be the guess this
      function exists to replace;
    * anything that is not plain scalar text is ignored, since a dict or list has no single
      submission form.

    A source that cannot be read or parsed yields nothing. Failing closed here costs a
    reference; failing open would invent one.
    """
    reader = _DataFieldReader()
    for fn in vf_task.hooks("reward"):
        try:
            source = textwrap.dedent(inspect.getsource(fn))
            reader.visit(ast.parse(source))
        except (OSError, TypeError, SyntaxError, ValueError, RecursionError):
            # Builtins and C callables have no source; a decorated or dynamically built
            # reward may not dedent to something parseable. Neither is our business.
            continue

    candidates = sorted(reader.fields - _NEVER_A_REFERENCE)
    if len(candidates) != 1:
        return None

    value = getattr(vf_task.data, candidates[0], None)
    if value is None or isinstance(value, (bool, dict, list, tuple, set)):
        return None
    text = str(value).strip()
    return text or None


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

    The list was hard-coded here until it became what it always was — an informal set of
    metamorphic relations. It now comes from :mod:`bohrin.relations`, where each rewriting
    carries the argument for why it preserves meaning and a third party can add their own
    without patching Bohrin. This function keeps the flat shape its callers expect; use
    :func:`bohrin.relations.renderings` when the relation's id is wanted too.
    """
    return [rendering for _relation_id, rendering in relation_renderings(answer)]


def _taskset_id(path: Path) -> str | None:
    """The taskset id for a package directory.

    Upstream resolves an id (`owner/name`, or a bare `name`) to an *installed* module, so
    the id is the distribution name from the package's own pyproject.
    """
    return distribution_name(path)


def _require_bounded(taskset: Any, taskset_id: str) -> None:
    """Refuse a taskset that generates tasks forever.

    `head` clears ``INFINITE`` on the view it returns, so this runs after any
    ``--max-tasks`` bound has been applied. The probes materialise the task list before
    scoring, so an unbounded infinite taskset does not fail — it hangs with no output,
    which is the worst way for a tool to be wrong.
    """
    if getattr(taskset, "INFINITE", False):
        raise MissingExtraError(
            f"taskset {taskset_id!r} is infinite — it generates tasks on demand, forever. "
            f"Bound it with --max-tasks N to audit a prefix of it."
        )


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

    def check_requirements(self) -> None:
        if not _available():
            raise MissingExtraError(
                "this looks like a verifiers taskset; reading it requires: pip install 'bohrin[verifiers]'"
            )

    def load(self, path: Path, config: ScanConfig) -> TaskSource:
        self.check_requirements()
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
        except Exception as exc:
            # Deliberately broad. These two calls import the taskset's package and run its
            # module-level code, so the exception type is whatever the customer's code (or
            # a version-drifted `verifiers`) happens to raise — AttributeError, TypeError,
            # KeyError, a bare RuntimeError. Enumerating them is guesswork that fails open
            # into a traceback; the boundary is what is knowable, not the type.
            raise TasksetLoadError(
                f"taskset {taskset_id!r} is installed but failed to load: "
                f"{type(exc).__name__}: {exc}. This is an error inside the taskset or its "
                f"`verifiers` version, not inside Bohrin — the audit never started. Check "
                f"that the taskset imports on its own (python -c 'import {taskset_id}')."
            ) from exc
        #: Tasks before --max-tasks bounded them, when the taskset can say so cheaply.
        #:
        #: A v1 taskset is an iterable and upstream does not currently give it a ``__len__``,
        #: so this is usually ``None`` and the report simply omits the corpus size. Counting
        #: by iteration is deliberately not done: it would construct every task in the
        #: taskset on every run, including the runs that passed ``--max-tasks`` precisely
        #: because the taskset is large. Paying an unbounded cost to print a coverage number
        #: is a worse trade than not printing it, and ``None`` is read as "cannot say"
        #: rather than "not truncated".
        self.corpus_total: int | None = None
        if not getattr(taskset, "INFINITE", False):
            try:
                self.corpus_total = len(taskset)
            except (TypeError, AttributeError):
                self.corpus_total = None
        if config.max_tasks is not None:
            taskset = taskset.head(config.max_tasks)
        _require_bounded(taskset, taskset_id)
        self._taskset = taskset
        #: Bohrin task id -> the upstream task object, populated by tasks().
        self._by_id: dict[str, Any] = {}

    def tasks(self) -> Iterator[Task]:
        for index, vf_task in enumerate(self._taskset):
            data = vf_task.data
            reward_fns = tuple(fn.__name__ for fn in vf_task.hooks("reward"))
            needs_runtime = tuple(fn.__name__ for fn in vf_task.hooks("reward") if _requires_runtime(fn))

            task_id = str(getattr(data, "name", None) or getattr(data, "idx", None) or index)
            self._by_id[task_id] = vf_task

            yield Task(
                id=task_id,
                prompt=str(getattr(data, "prompt", "") or getattr(data, "description", "") or ""),
                # Name-based lookup first (cheap, and the convention most tasksets follow),
                # then the reward function's own contract for the ones that named it otherwise.
                reference=_first_reference(data) or _reference_by_contract(vf_task),
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
            # Tolerance for float summation of the weights, not for the reward's scale.
            scale_exceeded=bool(attainable) and total > attainable + 1e-9,
        )


__all__ = ["VerifiersV1Adapter", "reference_renderings"]
