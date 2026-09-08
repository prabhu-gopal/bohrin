"""Reads a legacy `verifiers` environment — the ``load_environment`` API.

Upstream has moved to the v1 taskset API and files the older one under
``verifiers.legacy``, but the published ecosystem has not followed yet: in Prime
Intellect's environments repository, 111 modules define ``load_environment`` and none
defines a v1 taskset. Auditing only v1 would mean auditing almost nothing that is
actually published, so both APIs are supported and the adapter layer is where that
difference is absorbed — the probes never learn about it.

The two adapters never contend for a path: :meth:`detect` yields to ``verifiers_v1``
whenever a ``taskset.py`` is present, so a migrated environment is read as v1.
"""

from __future__ import annotations

import ast
import inspect
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bohrin.adapters._package import distribution_name
from bohrin.adapters.base import Adapter, MissingExtraError, TasksetLoadError, TaskSource
from bohrin.ir.task import Candidate, Task, Verdict

if TYPE_CHECKING:
    from bohrin.config import ScanConfig

#: The function a legacy environment module exposes.
_ENTRY = "load_environment"

#: The file whose presence means the v1 adapter owns this path.
_V1_MARKER = "taskset.py"

#: Directories that never hold the environment module, skipped so detection stays cheap on
#: a repository that also vendors data, results or a virtualenv.
_SKIP_DIRS = frozenset({".git", ".venv", "venv", "__pycache__", "node_modules", "outputs", "data"})

#: How deep below the given path to look for the module. Published environments put it at
#: the top or one level down; scanning further turns detection into a repository crawl.
_MAX_DEPTH = 2

#: Row fields commonly holding a known-good answer, in preference order.
_REFERENCE_FIELDS = ("answer", "solution", "reference", "expected", "target", "ground_truth")

#: The logger upstream reports a failing reward function on. It catches the exception,
#: logs it, and records the function's score as zero — so a rubric that could not be
#: evaluated is indistinguishable, by its numbers alone, from one that scored zero
#: honestly. Watching this logger is the only signal that the difference exists.
_VERIFIERS_LOGGER = "verifiers"

#: Parameters that only a live rollout can supply. A reward function taking one of these
#: without a default cannot be scored offline, and scoring it anyway would award marks on a
#: partial rubric — which manufactures exploits that are artefacts of the audit.
_RUNTIME_PARAMS = frozenset({"client", "judge_client", "judge", "model", "sampling_args"})


def _available() -> bool:
    try:
        import verifiers  # noqa: F401
    except ImportError:
        return False
    return True


def _defines_entry(module: Path) -> bool:
    """Whether ``module`` defines a top-level ``load_environment``.

    Parsed, not pattern-matched. A regex over the source also matches the name inside a
    comment, a docstring or an import line, and detection that fires on a mention rather
    than a definition claims paths this adapter cannot actually load.
    """
    try:
        tree = ast.parse(module.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError, UnicodeDecodeError):
        # Unreadable or unparseable is "not a match", never an error: detection runs over
        # whatever files happen to sit in the directory.
        return False
    return any(isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == _ENTRY for node in tree.body)


def _entry_module(path: Path) -> Path | None:
    """The first module under ``path`` defining ``load_environment``, or None."""
    for depth in range(_MAX_DEPTH + 1):
        for module in sorted(path.glob("/".join(["*"] * depth + ["*.py"]))):
            if any(part in _SKIP_DIRS for part in module.relative_to(path).parts):
                continue
            if _defines_entry(module):
                return module
    return None


def _requires_runtime(fn: Callable[..., Any]) -> bool:
    """Whether ``fn`` needs a live rollout, and so cannot be scored offline."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # builtins and C callables have no signature
        return False
    return any(name in _RUNTIME_PARAMS and param.default is inspect.Parameter.empty for name, param in params.items())


class _ErrorCapture(logging.Handler):
    """Collects the messages upstream logs when a reward function raises."""

    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@contextmanager
def _captured_reward_errors() -> Any:
    """Capture, and silence, upstream's per-reward-function error logging.

    Silenced because it is emitted once per reward function per scored candidate: an audit
    of fifteen tasks turns a single broken rubric into hundreds of identical stderr lines
    that bury the report. Nothing is lost — the messages are attached to the verdict and
    reported once, as a refusal to score, which is the actionable form of the same fact.
    """
    logger = logging.getLogger(_VERIFIERS_LOGGER)
    handler = _ErrorCapture()
    previous = logger.propagate
    logger.addHandler(handler)
    logger.propagate = False
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.propagate = previous


def _scoring_funcs(rubric: Any) -> list[tuple[Callable[..., Any], float]]:
    """Every weighted reward function in ``rubric``, flattened.

    A rubric may be a group of rubrics, and a group's own ``funcs`` list is empty while its
    children carry the real ones. Zero-weight entries are metrics rather than rewards —
    upstream records them alongside the score — so they are excluded here; counting them as
    attainable reward would make full marks unreachable and every candidate look rejected.
    """
    out: list[tuple[Callable[..., Any], float]] = []
    funcs = list(getattr(rubric, "funcs", []) or [])
    weights = list(getattr(rubric, "weights", []) or [])
    for index, fn in enumerate(funcs):
        weight = float(weights[index]) if index < len(weights) else 1.0
        if weight:
            out.append((fn, weight))
    for child in getattr(rubric, "rubrics", []) or []:
        out.extend(_scoring_funcs(child))
    return out


def _prompt_text(row: dict[str, Any]) -> str:
    """The question as a probe can read it.

    ``prompt`` is a chat message list in this API; ``question`` is the plain string the
    same row usually also carries. Preferring the string keeps operators that quote the
    prompt (``identity_return``) producing something a human can check.
    """
    question = row.get("question")
    if isinstance(question, str) and question.strip():
        return question
    prompt = row.get("prompt")
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, list):
        parts = [str(m.get("content", "")) for m in prompt if isinstance(m, dict)]
        return "\n\n".join(p for p in parts if p)
    return ""


def _reference(row: dict[str, Any]) -> str | None:
    """A known-good answer from the row, or None when it carries none.

    An empty string is not a reference. Rows in this API frequently set ``answer`` to ``""``
    when the grading is done from ``info`` instead, and treating that as a known-good answer
    would let a differential operator claim the verifier accepted "nothing" as correct.
    """
    for field in _REFERENCE_FIELDS:
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return None


class VerifiersLegacyAdapter(Adapter):
    """Reads a `verifiers` environment built on ``load_environment``."""

    name = "verifiers_legacy"

    def detect(self, path: Path) -> float:
        """Detect from files alone, so an uninstalled extra still gives a clear error.

        Yields to ``verifiers_v1`` on any path holding a ``taskset.py``: an environment that
        has migrated should be read through the API it migrated to.
        """
        if not path.is_dir():
            return 0.0
        if any(path.rglob(_V1_MARKER)):
            return 0.0
        if _entry_module(path) is None:
            return 0.0
        return 0.9 if distribution_name(path) else 0.7

    def check_requirements(self) -> None:
        if not _available():
            raise MissingExtraError(
                "this looks like a verifiers environment; reading it requires: pip install 'bohrin[verifiers]'"
            )

    def load(self, path: Path, config: ScanConfig) -> TaskSource:
        self.check_requirements()
        env_id = distribution_name(path)
        if env_id is None:
            raise MissingExtraError(
                f"found a {_ENTRY}() module under {str(path)!r} but no pyproject.toml naming the package. "
                f"A verifiers environment is an installed Python package; install it first, e.g. "
                f"pip install -e {str(path)!r}"
            )
        return _LegacySource(env_id, config)


class _LegacySource:
    """A loaded legacy environment, exposed through Bohrin's task interface."""

    def __init__(self, env_id: str, config: ScanConfig) -> None:
        import verifiers as vf

        self._id = env_id
        self._config = config
        try:
            env = vf.load_environment(env_id)
        except ModuleNotFoundError as exc:
            raise MissingExtraError(
                f"environment {env_id!r} is not installed. A verifiers environment is an installed "
                f"Python package — install it first (pip install -e <path>) and re-run. ({exc})"
            ) from exc
        except Exception as exc:
            # Deliberately broad, for the reason documented on TasksetLoadError: this call
            # imports the customer's package and runs its module-level code, so the
            # exception type is whatever that code raises.
            raise TasksetLoadError(
                f"environment {env_id!r} is installed but failed to load: "
                f"{type(exc).__name__}: {exc}. This is an error inside the environment or its "
                f"`verifiers` version, not inside Bohrin — the audit never started. Check "
                f"that it imports on its own (python -c 'import {env_id}')."
            ) from exc

        self._env = env
        self._rubric = env.rubric
        self._scoring = _scoring_funcs(env.rubric)
        # Full marks, for deciding acceptance. Summed once: a rubric is fixed for the run.
        self._attainable = sum(weight for _, weight in self._scoring)
        try:
            dataset = env.get_dataset(n=config.max_tasks) if config.max_tasks is not None else env.get_dataset()
        except Exception as exc:
            raise TasksetLoadError(
                f"environment {env_id!r} loaded but its dataset could not be read: "
                f"{type(exc).__name__}: {exc}. This is an error inside the environment, not "
                f"inside Bohrin — the audit never started."
            ) from exc
        self._rows: list[dict[str, Any]] = [dict(row) for row in dataset]
        #: Bohrin task id -> its row, populated by tasks().
        self._by_id: dict[str, dict[str, Any]] = {}

    def tasks(self) -> Iterator[Task]:
        reward_fns = tuple(getattr(fn, "__name__", repr(fn)) for fn, _ in self._scoring)
        needs_runtime = tuple(getattr(fn, "__name__", repr(fn)) for fn, _ in self._scoring if _requires_runtime(fn))

        for index, row in enumerate(self._rows):
            task_id = str(row.get("example_id", index))
            self._by_id[task_id] = row
            yield Task(
                id=task_id,
                prompt=_prompt_text(row),
                reference=_reference(row),
                reward_fns=reward_fns,
                metadata={
                    "taskset": self._id,
                    "task_type": type(self._env).__name__,
                    "key": str(row.get("task", "")),
                    "requires_runtime": needs_runtime,
                    "offline_scoreable": not needs_runtime,
                },
            )

    def _state_for(self, row: dict[str, Any], payload: str) -> Any:
        """A rollout state whose single assistant reply is ``payload``.

        ``State`` forwards the input fields upstream reward functions read by name, so the
        row is passed through as the rollout input rather than being flattened.
        """
        from verifiers.legacy.types import State

        return State(
            input={
                "prompt": row.get("prompt", []),
                "answer": row.get("answer", ""),
                "info": row.get("info", {}),
                "example_id": row.get("example_id", 0),
            },
            task={"name": str(row.get("task", ""))},
            completion=[{"role": "assistant", "content": payload}],
            trajectory=[],
            is_completed=True,
            is_truncated=False,
        )

    async def score(self, task: Task, candidate: Candidate) -> Verdict:
        row = self._by_id.get(task.id)
        if row is None:
            raise KeyError(f"task {task.id!r} was not produced by this source")

        if task.metadata.get("requires_runtime"):
            names = ", ".join(task.metadata["requires_runtime"])
            raise RuntimeError(
                f"task {task.id!r} has reward function(s) requiring a live rollout ({names}). "
                f"Scoring offline would skip them and award full marks on a partial rubric, "
                f"which manufactures false exploits. Run with a runtime, or exclude this task."
            )

        state = self._state_for(row, candidate.payload)
        # score_rollout reports through the state it is given rather than by returning.
        with _captured_reward_errors() as errors:
            await self._rubric.score_rollout(state)

        if errors.messages:
            # Upstream scores a raising reward function as zero and continues, so the total
            # that comes back is a partial rubric wearing a complete rubric's number. Every
            # verdict derived from it is unsound in both directions: a candidate cannot
            # reach full marks, so nothing is ever reported as accepted, and the known-good
            # answer fails too, which reads as a verifier that rejects its own ground truth.
            # Refusing the task is the only honest option, and the probe excludes it by name.
            first = errors.messages[0]
            raise RuntimeError(
                f"task {task.id!r}: {len(errors.messages)} reward function call(s) raised while "
                f"scoring, so the rubric was only partially evaluated. A score from a partial "
                f"rubric manufactures findings in both directions, so this task is not scored. "
                f"This usually means the reward functions read rollout state that only a live "
                f"multi-turn rollout produces. First error: {first}"
            )

        reward = state.get("reward")
        total = float(reward) if reward is not None else 0.0
        metrics = state.get("metrics") or {}
        per_fn = {name: float(value) for name, value in metrics.items() if isinstance(value, int | float)}

        return Verdict(
            reward=total,
            passed=bool(self._attainable) and total >= self._attainable,
            per_fn=per_fn,
            raw={
                "attainable": self._attainable,
                "declared_rewards": list(task.reward_fns),
            },
        )


__all__ = ["VerifiersLegacyAdapter"]
