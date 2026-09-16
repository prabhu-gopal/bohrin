"""Adapter for Inspect evaluation tasks.

`Inspect <https://inspect.aisi.org.uk/>`_ describes an evaluation as a ``@task`` function
returning a ``Task``: a dataset of samples, a solver that produces the model's reply, and one
or more scorers that grade it. A scorer is an async callable over a ``TaskState`` and the
sample's ``Target``, so a candidate is scored the same way the ``verifiers`` adapters score
one: build the state a finished sample would have, with the candidate as the model's output,
and call the scorer directly. No solver runs and no model is asked anything.

Everything below was established against ``inspect_ai`` 0.3.263 by introspection. Two of the
load-bearing details are private, and a test pins them so that an upstream change fails the
build rather than silently changing audits.

**What cannot be scored this way, and how it is refused.** A scorer that asks a model to
grade, or runs commands in a sandbox, cannot be called offline. Scoring it anyway produces a
number that says nothing about the grader, so such tasks are refused -- never scored as
clean, and never reported as broken. Refusal happens at two points:

* *Before scoring*, from what the task declares: a sandbox on the task or the sample, a
  model-graded built-in scorer, or ``choice``, which reads answers the multiple-choice
  solver marks and so rejects every reply that did not pass through that solver.
* *While scoring*, for everything a declaration cannot show. A custom scorer can call a
  model for only some replies -- an exact match first, a judge as the fallback -- and can
  catch the resulting error and return "incorrect". Left alone, the first case would look
  like the grader crashing on Bohrin's submission, and the second like the grader rejecting
  a correct answer: two false accusations. So every route to a model or a sandbox is
  intercepted for the duration of a Bohrin score call, the attempt is recorded even when the
  scorer swallows the error, and the submission is declined with
  :class:`~bohrin.adapters.base.ScoringRefused`, which the audit never counts as a defect.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextvars import ContextVar
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from bohrin.adapters.base import (
    Adapter,
    MissingExtraError,
    RewardFunctionError,
    ScoringRefused,
    TasksetLoadError,
    TaskSource,
)
from bohrin.adapters.selection import select_indices
from bohrin.ir.task import Candidate, Task, Verdict

if TYPE_CHECKING:
    from bohrin.config import ScanConfig

#: Built-in scorers that call a model to grade. Custom scorers that do the same are caught
#: while scoring instead; see the module docstring.
_MODEL_GRADED = frozenset({"model_graded_qa", "model_graded_fact"})

#: Built-in scorers that grade state a solver prepares rather than the reply itself.
_SOLVER_STATE = frozenset({"choice"})

#: The model name a synthetic ``TaskState`` carries. Nothing resolves it; it only has to parse.
_NO_MODEL = "bohrin/none"

#: Recorded routes to a model or sandbox during the current Bohrin score call, or ``None``
#: outside one. Outside a score call every intercepted function behaves exactly as upstream.
_attempted: ContextVar[list[str] | None] = ContextVar("bohrin_inspect_attempted", default=None)

_guards_installed = False

#: ``id`` of each original function that is rebound -> its guarded replacement.
_replacements: dict[int, Any] = {}


class _RuntimeCallRefused(Exception):
    """Raised into a scorer that reached for a model or a sandbox during a Bohrin score call."""


def _available() -> bool:
    try:
        importlib.import_module("inspect_ai")
    except ImportError:
        return False
    return True


def _mentions_inspect_task(path: Path) -> bool:
    """Whether a Python file imports Inspect and defines a ``@task``. Reads text only."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "inspect_ai" in text and "@task" in text


def _task_files(path: Path) -> list[Path]:
    """The files an audit of ``path`` reads: the file itself, or a directory's own files.

    A directory is not searched recursively. An evaluation collection holds hundreds of
    tasks, and auditing one of them should not import every other.
    """
    if path.is_file():
        return [path] if path.suffix == ".py" and _mentions_inspect_task(path) else []
    if path.is_dir():
        return sorted(p for p in path.glob("*.py") if _mentions_inspect_task(p))
    return []


def _import_file(path: Path) -> ModuleType:
    """Import a task file the way Inspect would find it.

    A file inside a package is imported by its dotted name, so the package's own relative and
    absolute imports resolve. A loose file is imported under a private name.
    """
    path = path.resolve()
    parts = [path.stem]
    root = path.parent
    while (root / "__init__.py").exists():
        parts.insert(0, root.name)
        root = root.parent
    if len(parts) > 1:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        return importlib.import_module(".".join(parts))
    name = f"_bohrin_inspect_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {str(path)!r}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses and pydantic models look their module up by name
    spec.loader.exec_module(module)
    return module


def _registry() -> Any:
    return importlib.import_module("inspect_ai._util.registry")


def _task_factories(module: ModuleType) -> list[tuple[str, Callable[[], Any]]]:
    """The ``@task`` functions defined in ``module`` itself, not ones it imported."""
    registry = _registry()
    found: list[tuple[str, Callable[[], Any]]] = []
    for obj in vars(module).values():
        if not callable(obj) or getattr(obj, "__module__", None) != module.__name__:
            continue
        if registry.is_registry_object(obj, type="task"):
            found.append((str(registry.registry_unqualified_name(obj)), obj))
    return sorted(found, key=lambda pair: pair[0])


def _scorer_name(scorer: Any) -> str:
    try:
        return str(_registry().registry_unqualified_name(scorer))
    except Exception:  # a scorer that was never registered still has a Python name
        return str(getattr(scorer, "__name__", type(scorer).__name__))


def _text(value: Any) -> str:
    """A sample input as plain text: a string, or the text of a list of chat messages."""
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return "\n\n".join(str(getattr(message, "text", "")) for message in value)
    return str(value)


def _reference(target: Any) -> str | None:
    """The sample's target as the one known-good answer, or ``None`` when there is not one.

    A list target means *any* of its items is correct. Picking one as "the" answer turns every
    other item into a known-wrong candidate, and a grader accepting it into a false accusation.
    Measured on ``inspect_evals/drop``: a sample whose target is ``['2', '1']`` was reported as
    accepting the wrong answer ``1``. So a list with more than one distinct answer declares no
    reference, and the task is probed with the checks that need none.
    """
    if isinstance(target, str):
        return target.strip() or None
    if isinstance(target, Sequence):
        answers = {str(item).strip() for item in target} - {""}
        if len(answers) == 1:
            return answers.pop()
    return None


def _install_guards() -> None:
    """Intercept every route from a scorer to a model or a sandbox. Idempotent.

    ``get_model`` and ``sandbox`` are usually imported by name (``from inspect_ai.model
    import get_model``), so replacing them in their defining module alone reaches nobody who
    already holds a reference. Every loaded module holding the original is therefore
    rebound, and the two constructors that any remaining path must pass through --
    ``active_model`` and ``Model.__init__`` -- are wrapped as well. Called after task files
    are imported, so their references are rebound too.
    """
    global _guards_installed
    model_mod = importlib.import_module("inspect_ai.model._model")
    sandbox_mod = importlib.import_module("inspect_ai.util._sandbox.context")

    def refuse(route: str) -> None:
        seen = _attempted.get()
        if seen is not None:
            seen.append(route)
            raise _RuntimeCallRefused(f"the scorer tried to use {route}")

    if not _guards_installed:
        originals: dict[str, Any] = {
            "get_model": model_mod.get_model,
            "active_model": model_mod.active_model,
            "sandbox": sandbox_mod.sandbox,
        }
        original_init = model_mod.Model.__init__

        def get_model(*args: Any, **kwargs: Any) -> Any:
            refuse("a model")
            return originals["get_model"](*args, **kwargs)

        def active_model(*args: Any, **kwargs: Any) -> Any:
            refuse("a model")
            return originals["active_model"](*args, **kwargs)

        def sandbox(*args: Any, **kwargs: Any) -> Any:
            refuse("a sandbox")
            return originals["sandbox"](*args, **kwargs)

        def model_init(self: Any, *args: Any, **kwargs: Any) -> None:
            refuse("a model")
            original_init(self, *args, **kwargs)

        _replacements[id(originals["get_model"])] = get_model
        _replacements[id(originals["sandbox"])] = sandbox
        setattr(model_mod, "active_model", active_model)  # noqa: B010 - a module attribute, rebound on purpose
        model_mod.Model.__init__ = model_init
        _guards_installed = True

    for module in list(sys.modules.values()):
        namespace = getattr(module, "__dict__", None)
        if not isinstance(namespace, dict):
            continue
        for attr in ("get_model", "sandbox"):
            held = namespace.get(attr)
            if held is not None and id(held) in _replacements:
                namespace[attr] = _replacements[id(held)]


class InspectAdapter(Adapter):
    """Reads Inspect ``@task`` files."""

    name = "inspect"

    def detect(self, path: Path) -> float:
        """Detect from file text alone, so an uninstalled extra still gives a clear error."""
        if path.is_file():
            return 0.9 if _task_files(path) else 0.0
        if path.is_dir() and _task_files(path):
            return 0.8
        return 0.0

    def check_requirements(self) -> None:
        if not _available():
            raise MissingExtraError(
                "this looks like an Inspect task file; reading it requires: pip install 'bohrin[inspect]'"
            )

    def load(self, path: Path, config: ScanConfig) -> TaskSource:
        self.check_requirements()
        files = _task_files(path)
        if not files:
            raise TasksetLoadError(f"no Inspect @task found in {str(path)!r}")
        return _InspectSource(files, config)


class _InspectSource:
    """Loaded Inspect tasks, one Bohrin task per sample."""

    def __init__(self, files: Sequence[Path], config: ScanConfig) -> None:
        self._config = config
        loaded: list[tuple[str, Any]] = []
        for file in files:
            try:
                module = _import_file(file)
            except Exception as exc:
                raise TasksetLoadError(
                    f"Inspect task file {str(file)!r} failed to import: {type(exc).__name__}: {exc}. "
                    f"This is an error inside the task file or its dependencies, not inside Bohrin."
                ) from exc
            for task_name, factory in _task_factories(module):
                try:
                    loaded.append((task_name, factory()))
                except Exception as exc:
                    # Calling the factory builds the dataset, which may download it. A task
                    # that needs arguments or a network it does not have fails here.
                    raise TasksetLoadError(
                        f"Inspect task {task_name!r} failed to build: {type(exc).__name__}: {exc}. "
                        f"Tasks are built with no arguments; one that needs them, or a dataset "
                        f"download that is unavailable, cannot be audited as it stands."
                    ) from exc
        if not loaded:
            raise TasksetLoadError(f"no Inspect @task function is defined in {', '.join(map(str, files))}")
        _install_guards()

        #: (task name, task, sample index) for every sample, in file and dataset order.
        self._samples = [(name, task, index) for name, task in loaded for index in range(len(task.dataset))]
        self.corpus_total: int | None = len(self._samples)
        try:
            indices, self.selection_mode = select_indices(self.corpus_total, config.max_tasks, config.sample_seed)
        except ValueError as exc:  # unreachable while the length is known; kept for the contract
            raise TasksetLoadError(str(exc)) from exc
        if indices is None:
            bound = config.max_tasks if config.max_tasks is not None else len(self._samples)
            indices = list(range(min(bound, len(self._samples))))
        self._selected = indices
        self.selection_seed: int | None = config.sample_seed if self.selection_mode == "random" else None
        self._by_id: dict[str, tuple[Any, Any]] = {}
        self._multiple_tasks = len(loaded) > 1

    def tasks(self) -> Iterator[Task]:
        for position in self._selected:
            task_name, inspect_task, index = self._samples[position]
            sample = inspect_task.dataset[index]
            sample_id = sample.id if sample.id is not None else index
            task_id = f"{task_name}/{sample_id}"
            self._by_id[task_id] = (inspect_task, sample)

            scorers = list(inspect_task.scorer or [])
            names = tuple(_scorer_name(s) for s in scorers)
            refused: list[str] = []
            if inspect_task.sandbox is not None or getattr(sample, "sandbox", None) is not None:
                refused.extend(f"{name} (the task runs in a sandbox)" for name in names)
            else:
                refused.extend(f"{name} (calls a model to grade)" for name in names if name in _MODEL_GRADED)
                refused.extend(
                    f"{name} (grades choices the multiple-choice solver marks)"
                    for name in names
                    if name in _SOLVER_STATE
                )

            yield Task(
                id=task_id,
                prompt=_text(sample.input),
                reference=_reference(sample.target),
                reward_fns=names,
                metadata={
                    "inspect_task": task_name,
                    "requires_runtime": tuple(refused),
                    "offline_scoreable": not refused,
                },
            )

    def _state(self, sample: Any, payload: str) -> Any:
        """The ``TaskState`` a finished sample would carry, with ``payload`` as the reply."""
        model = importlib.import_module("inspect_ai.model")
        solver = importlib.import_module("inspect_ai.solver")
        scorer = importlib.import_module("inspect_ai.scorer")
        messages = (
            [model.ChatMessageUser(content=sample.input)] if isinstance(sample.input, str) else list(sample.input)
        )
        messages.append(model.ChatMessageAssistant(content=payload))
        return solver.TaskState(
            model=_NO_MODEL,
            sample_id=sample.id if sample.id is not None else 0,
            epoch=1,
            input=sample.input,
            messages=messages,
            target=scorer.Target(sample.target),
            choices=sample.choices,
            output=model.ModelOutput.from_content(_NO_MODEL, payload),
            metadata=dict(sample.metadata or {}),
            completed=True,
        )

    async def score(self, task: Task, candidate: Candidate) -> Verdict:
        found = self._by_id.get(task.id)
        if found is None:
            raise KeyError(f"task {task.id!r} was not produced by this source")
        inspect_task, sample = found
        if task.metadata.get("requires_runtime"):
            raise ScoringRefused(
                f"task {task.id!r} cannot be scored offline: {', '.join(task.metadata['requires_runtime'])}"
            )

        scorer_mod = importlib.import_module("inspect_ai.scorer")
        to_float = scorer_mod.value_to_float()
        per_fn: dict[str, float] = {}
        passed = True
        seen: list[str] = []
        token = _attempted.set(seen)
        name = ""
        try:
            for scorer, name in zip(inspect_task.scorer or [], task.reward_fns, strict=True):
                result = await scorer(self._state(sample, candidate.payload), scorer_mod.Target(sample.target))
                values = _score_values(result.value if result is not None else 0, to_float)
                per_fn[name] = sum(values) / len(values)
                passed = passed and min(values) >= 1.0
        except Exception as exc:
            if seen:
                raise ScoringRefused(
                    f"task {task.id!r}: scorer {name!r} tried to use {seen[0]} while grading, which "
                    f"cannot be done offline; this submission was not scored"
                ) from exc
            raise RewardFunctionError(
                f"task {task.id!r}: scorer {name!r} raised while grading this submission",
                reward_error=f"{type(exc).__name__}: {exc}",
            ) from exc
        finally:
            _attempted.reset(token)
        if seen:
            # The scorer reached for a model or sandbox and handled the failure itself, so the
            # score it returned describes that failure, not the submission.
            raise ScoringRefused(
                f"task {task.id!r}: a scorer tried to use {seen[0]} while grading and handled the "
                f"refusal itself, so its score does not describe this submission"
            )

        reward = sum(per_fn.values()) / len(per_fn) if per_fn else 0.0
        return Verdict(
            reward=reward,
            passed=bool(per_fn) and passed,
            per_fn=per_fn,
            raw={"inspect_task": task.metadata.get("inspect_task")},
            scale_exceeded=any(value > 1.0 + 1e-9 for value in per_fn.values()),
        )


def _score_values(value: Any, to_float: Callable[[Any], float]) -> list[float]:
    """A score's value as floats. A mapping or list of values is graded item by item."""
    if isinstance(value, Mapping):
        items = [to_float(v) for v in value.values() if v is not None]
    elif isinstance(value, Sequence) and not isinstance(value, str):
        items = [to_float(v) for v in value]
    else:
        items = [to_float(value)]
    return items or [0.0]


__all__ = ["InspectAdapter"]
