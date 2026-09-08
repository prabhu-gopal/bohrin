"""The verifiers v1 adapter, tested against the real library.

These tests skip when the optional extra is absent, but they are not optional in CI: the
adapter re-implements a private upstream behaviour (`Task.score`'s runtime filtering), and
if upstream changes it, the failure must surface here rather than as silently wrong audits
in front of a customer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bohrin.adapters.base import TasksetLoadError
from bohrin.adapters.verifiers_v1 import (
    VerifiersV1Adapter,
    _first_reference,
    _requires_runtime,
    _taskset_id,
)
from bohrin.config import ScanConfig
from bohrin.ir.task import Candidate, Provenance, Task

vf = pytest.importorskip("verifiers.v1", reason="the verifiers extra is not installed")


# --------------------------------------------------------------------------- fixtures


class _Data(vf.TaskData):
    answer: int = 42


class _OfflineTask(vf.Task[_Data]):
    """Fully scoreable without a runtime."""

    @vf.reward
    async def exact_match(self, trace: Any) -> float:
        return float(trace.last_reply == str(self.data.answer))

    @vf.reward
    async def non_empty(self, trace: Any) -> float:
        return float(bool(trace.last_reply.strip()))


class _RuntimeTask(vf.Task[_Data]):
    """One reward needs a container; scoring it offline would be a partial rubric."""

    @vf.reward
    async def non_empty(self, trace: Any) -> float:
        return float(bool(trace.last_reply.strip()))

    @vf.reward
    async def runs_the_tests(self, trace: Any, runtime: Any) -> float:
        return 0.0


def _cand(payload: str) -> Candidate:
    return Candidate(payload=payload, provenance=Provenance(operator="t", base="constant", detail="test"))


def _source_with(vf_task: Any, task: Task) -> Any:
    """A source bound to one already-constructed upstream task, bypassing package loading."""
    from bohrin.adapters.verifiers_v1 import _VerifiersSource

    source = object.__new__(_VerifiersSource)
    source._vf = vf
    source._id = "test"
    source._config = ScanConfig()
    source._taskset = None
    source._by_id = {task.id: vf_task}
    return source


# ------------------------------------------------------------------ the runtime trap


def test_requires_runtime_matches_upstreams_own_rule() -> None:
    """Pins a private upstream behaviour we re-implement.

    `Task.score` drops rewards whose signature has a non-defaulted `runtime` parameter.
    If that rule changes upstream, this test fails — which is the point.
    """
    offline = {fn.__name__: fn for fn in _OfflineTask(data=_Data()).hooks("reward")}
    runtime = {fn.__name__: fn for fn in _RuntimeTask(data=_Data()).hooks("reward")}

    assert not _requires_runtime(offline["exact_match"])
    assert not _requires_runtime(offline["non_empty"])
    assert _requires_runtime(runtime["runs_the_tests"])
    assert not _requires_runtime(runtime["non_empty"])


async def test_offline_scoring_silently_drops_runtime_rewards() -> None:
    """The upstream behaviour this adapter exists to defend against.

    Demonstrated directly so the reason for the refusal below is not taken on trust.
    """
    task = _RuntimeTask(data=_Data())
    trace = vf.Trace(
        task=vf.TraceTask(type="t", data=task.data),
        agent=vf.AgentInfo(config=vf.AgentConfig()),
        nodes=[vf.MessageNode(message=vf.AssistantMessage(content="anything at all"), sampled=True)],
    )
    await task.score(trace)  # no runtime

    assert "runs_the_tests" not in trace.rewards, "the runtime reward is filtered before seeding"
    assert trace.rewards["non_empty"].score == 1.0
    # Full marks on a partial rubric: exactly the false exploit the adapter must refuse.
    assert trace.reward == 1.0


async def test_the_adapter_refuses_a_task_that_needs_a_runtime() -> None:
    """Refusing beats half-scoring: a partial rubric manufactures false exploits."""
    vf_task = _RuntimeTask(data=_Data())
    task = Task(
        id="t",
        prompt="p",
        reward_fns=("non_empty", "runs_the_tests"),
        metadata={"requires_runtime": ("runs_the_tests",)},
    )
    source = _source_with(vf_task, task)

    with pytest.raises(RuntimeError, match="requiring a runtime"):
        await source.score(task, _cand("anything"))


# ------------------------------------------------------------------- scoring semantics


@pytest.mark.parametrize(
    ("payload", "expect_pass"),
    [("42", True), ("7", False), ("", False)],
)
async def test_passing_requires_full_marks_not_a_partial_score(payload: str, expect_pass: bool) -> None:
    """A partial score is not acceptance.

    "7" earns non_empty but fails exact_match. Treating any positive reward as a pass
    would report a correct verifier as broken.
    """
    vf_task = _OfflineTask(data=_Data())
    task = Task(id="t", prompt="p", reward_fns=("exact_match", "non_empty"))
    source = _source_with(vf_task, task)

    verdict = await source.score(task, _cand(payload))

    assert verdict.passed is expect_pass
    assert verdict.raw["attainable"] == 2.0
    assert set(verdict.per_fn) == {"exact_match", "non_empty"}


async def test_the_submission_actually_reaches_the_verifier() -> None:
    """`sampled=True` is load-bearing.

    Without it `Trace.assistant_messages` skips the node and `last_reply` is empty, so
    every candidate would be scored as an empty submission and the audit would be
    quietly meaningless.
    """
    vf_task = _OfflineTask(data=_Data())
    task = Task(id="t", prompt="p", reward_fns=("exact_match", "non_empty"))
    source = _source_with(vf_task, task)

    trace = source._trace_for(vf_task, "42")
    assert trace.last_reply == "42", "the payload must be visible to the reward function"


# ------------------------------------------------------------------------- detection


def test_detection_reads_files_only(tmp_path: Path) -> None:
    root = tmp_path / "envs" / "demo"
    root.mkdir(parents=True)
    (root / "taskset.py").write_text("import verifiers.v1 as vf\n", encoding="utf-8")

    assert VerifiersV1Adapter().detect(tmp_path) == pytest.approx(0.7)
    (tmp_path / _pyproject()).write_text('[project]\nname = "demo-taskset"\n', encoding="utf-8")
    assert VerifiersV1Adapter().detect(tmp_path) == pytest.approx(0.95)
    assert _taskset_id(tmp_path) == "demo-taskset"


def _pyproject() -> str:
    return "pyproject.toml"


def test_a_directory_of_junk_is_not_claimed(tmp_path: Path) -> None:
    (tmp_path / "notes.md").write_text("hello", encoding="utf-8")
    assert VerifiersV1Adapter().detect(tmp_path) == 0.0


def test_an_uninstalled_taskset_says_how_to_install_it(tmp_path: Path) -> None:
    (tmp_path / "taskset.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "definitely-not-installed"\n', encoding="utf-8")

    from bohrin.adapters.base import MissingExtraError

    with pytest.raises(MissingExtraError, match="pip install"):
        VerifiersV1Adapter().load(tmp_path, ScanConfig())


def test_a_taskset_that_raises_while_loading_never_shows_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The blame inversion: a stack trace reads as "Bohrin crashed".

    Loading runs the customer's own module-level code, so the exception can be anything.
    ``ModuleNotFoundError`` was the only type handled, and everything else — the common
    case being a taskset written against a drifted ``verifiers`` API — escaped the CLI's
    user-error set as a raw traceback with exit 1.
    """
    (tmp_path / "taskset.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "exploding-taskset"\n', encoding="utf-8")

    def explode(_taskset_id: str) -> Any:
        raise AttributeError("module 'verifiers.legacy' has no attribute 'TaskData'")

    monkeypatch.setattr(vf, "taskset_config_type", explode)

    with pytest.raises(TasksetLoadError) as caught:
        VerifiersV1Adapter().load(tmp_path, ScanConfig())

    message = str(caught.value)
    assert "not inside Bohrin" in message, "the message must not let a reader blame the auditor"
    assert "AttributeError" in message, "the underlying cause must survive into the message"
    # Chained, so a debugger can still reach the original.
    assert isinstance(caught.value.__cause__, AttributeError)


def test_a_taskset_load_error_is_a_user_error_not_a_crash() -> None:
    """It must sit in the CLI's user-error set, or the message above never gets printed."""
    from bohrin.cli import _USER_ERRORS

    assert TasksetLoadError in _USER_ERRORS


# -------------------------------------------------------------------- reference lookup


def test_a_reference_is_read_when_present_and_never_guessed() -> None:
    class WithAnswer(vf.TaskData):
        answer: int = 7

    class WithNothing(vf.TaskData):
        pass

    assert _first_reference(WithAnswer()) == "7"
    assert _first_reference(WithNothing()) is None, "a missing reference must be None, never invented"


# ------------------------------------------------------------------------- reporting


def test_unmeasured_tasks_are_visible_in_the_terminal() -> None:
    """A silently reduced taskset lets a user believe the whole thing was audited."""
    import io

    from rich.console import Console

    from bohrin.probes.base import ProbeResult, ProbeStatus
    from bohrin.report.model import Report
    from bohrin.report.tty import render
    from bohrin.scoring.gap import verification_gap

    result = ProbeResult(
        probe_id="weak_oracle",
        status=ProbeStatus.OK,
        tasks_probed=3,
        sub_score=0.0,
        detail={
            "baseline_failures": [{"task_id": "99", "reward": 0.0, "reason": "needs a runtime"}],
            "baseline_errors": 1,
        },
    )
    report = Report(
        target="./t", adapter="verifiers_v1", gap=verification_gap([result], []), results=(result,), tasks_total=3
    )
    buffer = io.StringIO()
    render(report, Console(file=buffer, width=100, no_color=True))
    out = " ".join(buffer.getvalue().split())

    assert "could not be measured" in out
    assert "99" in out
    assert "excluded from its score" in out


# ------------------------------------------------------------------------- the read path


class _CountingTaskset(vf.Taskset[_OfflineTask, vf.TasksetConfig]):
    """Yields tasks forever, and records how many were actually built."""

    INFINITE = True

    def __init__(self, config: vf.TasksetConfig) -> None:
        super().__init__(config)
        self.built = 0

    def load(self) -> Any:
        while True:
            yield _OfflineTask(_Data(idx=self.built, prompt="p"), self.config.task)
            self.built += 1


def _source_over(taskset: Any) -> Any:
    from bohrin.adapters.verifiers_v1 import _VerifiersSource

    source = object.__new__(_VerifiersSource)
    source._vf = vf
    source._id = "test"
    source._config = ScanConfig()
    source._taskset = taskset
    source._by_id = {}
    return source


def test_max_tasks_actually_bounds_an_infinite_taskset() -> None:
    """`head` lives on the iteration path, so the adapter must iterate, not call `load`.

    Upstream is explicit that `load` is the subclass hook and `__iter__` is the read path:
    `head`/`shuffle` views and the config-layer system prompt are applied there. Calling
    `load()` directly discards the bound, and because the probes materialise the task list
    before scoring, an infinite taskset then hangs the audit forever with no output. That
    is exactly what a real environment (`color_codeword`) did.
    """
    taskset = _CountingTaskset(vf.TasksetConfig(id="test")).head(3)

    tasks = list(_source_over(taskset).tasks())

    assert len(tasks) == 3, "--max-tasks must bound the audit, not be silently discarded"


def test_the_configured_system_prompt_reaches_the_audited_task(tmp_path: Path) -> None:
    """Auditing a task without its system prompt audits a task that never runs.

    The config-layer system prompt is applied on the iteration path, so this is the second
    thing `load()` discarded. It reaches the verifier through the upstream task object the
    source keeps for scoring — not through Bohrin's own `Task.prompt`, which carries the
    task prompt an operator echoes.
    """
    prompt_file = tmp_path / "system.txt"
    prompt_file.write_text("You are being audited.", encoding="utf-8")

    taskset = _CountingTaskset(vf.TasksetConfig(id="test", system_prompt=prompt_file)).head(1)
    source = _source_over(taskset)
    (task,) = source.tasks()

    scored = source._by_id[task.id]
    assert scored.data.system_prompt == "You are being audited."


def test_an_unbounded_infinite_taskset_is_refused_not_hung() -> None:
    """Hanging with no output is the worst way for an audit to fail."""
    from bohrin.adapters.base import MissingExtraError
    from bohrin.adapters.verifiers_v1 import _require_bounded

    unbounded = _CountingTaskset(vf.TasksetConfig(id="test"))

    with pytest.raises(MissingExtraError, match="infinite"):
        _require_bounded(unbounded, "test")

    _require_bounded(unbounded.head(3), "test")  # bounded: no complaint
    assert unbounded.built == 0, "the guard must not build a single task to decide"


# ------------------------------------------------- reference discovery by contract


class _FakeData:
    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


class _FakeTask:
    """A stand-in exposing the two things contract discovery reads: hooks and data."""

    def __init__(self, data: Any, *rewards: Any) -> None:
        self.data = data
        self._rewards = rewards

    def hooks(self, _kind: str) -> tuple[Any, ...]:
        return self._rewards


def _reward_reading_word(self: Any, trace: Any) -> float:
    return float(self.data.word in (trace or ""))


def _reward_with_a_phantom_in_its_docstring(self: Any, trace: Any) -> float:
    """Grade the reply.

    Historically compared against self.data.answer, before the rename. See also
    getattr(self.data, "legacy_target") in the old harness.
    """
    # self.data.old_field is no longer read
    _marker = "self.data.phantom"
    return float(self.data.word in (trace or ""))


def _reward_reading_two_fields(self: Any, trace: Any) -> float:
    return float(self.data.word in (trace or "") and self.data.other in (trace or ""))


def _reward_reading_only_the_prompt(self: Any, trace: Any) -> float:
    return float(self.data.prompt in (trace or ""))


def test_a_reference_is_found_from_the_field_the_reward_actually_reads() -> None:
    """Name-based lookup asks whether the answer sits under a name we thought of.

    `scratchpad` stores its answer as `word` and grades with `self.data.word in answer`,
    so every one of its tasks was probed with no reference at all. The contract is
    readable from the reward itself.
    """
    from bohrin.adapters.verifiers_v1 import _reference_by_contract

    task = _FakeTask(_FakeData(word="alpha"), _reward_reading_word)
    assert _reference_by_contract(task) == "alpha"


def test_a_field_named_only_in_a_comment_or_docstring_is_not_a_contract() -> None:
    """Why this is parsed rather than pattern-matched.

    A regex over the source matches inside comments, docstrings and string literals. Here
    it would find four fields where the code reads one — and because discovery requires
    *exactly* one candidate, those phantoms would silently suppress a real reference.
    """
    from bohrin.adapters.verifiers_v1 import _reference_by_contract

    task = _FakeTask(
        _FakeData(word="alpha", answer="wrong", legacy_target="wrong", old_field="wrong", phantom="wrong"),
        _reward_with_a_phantom_in_its_docstring,
    )
    assert _reference_by_contract(task) == "alpha"


def test_two_candidate_fields_yield_nothing() -> None:
    """A wrong reference is worse than none: it becomes the baseline, and
    `constant_return` claims a differential ground against it. With two fields consulted
    there is no principled choice, and picking either is the guess this replaces."""
    from bohrin.adapters.verifiers_v1 import _reference_by_contract

    task = _FakeTask(_FakeData(word="alpha", other="beta"), _reward_reading_two_fields)
    assert _reference_by_contract(task) is None


def test_a_reward_reading_only_standard_fields_yields_nothing() -> None:
    """`self.data.prompt` is the question, not the answer. Submitting it as a known-good
    baseline would be nonsense, and would make every operator compare against it."""
    from bohrin.adapters.verifiers_v1 import _reference_by_contract

    task = _FakeTask(_FakeData(prompt="what is 2+2?"), _reward_reading_only_the_prompt)
    assert _reference_by_contract(task) is None


def test_a_getattr_access_is_recognised() -> None:
    from bohrin.adapters.verifiers_v1 import _reference_by_contract

    def reward(self: Any, trace: Any) -> float:
        return float(getattr(self.data, "codeword") in (trace or ""))  # noqa: B009

    task = _FakeTask(_FakeData(codeword="BAED"), reward)
    assert _reference_by_contract(task) == "BAED"


def test_an_unreadable_reward_fails_closed() -> None:
    """No source means no contract. Failing closed costs a reference; failing open
    invents one."""
    from bohrin.adapters.verifiers_v1 import _reference_by_contract

    task = _FakeTask(_FakeData(word="alpha"), len)  # a builtin has no source
    assert _reference_by_contract(task) is None


def test_a_non_scalar_field_is_not_a_reference() -> None:
    """A dict or list has no single submission form."""
    from bohrin.adapters.verifiers_v1 import _reference_by_contract

    def reward(self: Any, trace: Any) -> float:
        return float(bool(self.data.turns))

    assert _reference_by_contract(_FakeTask(_FakeData(turns=["a", "b"]), reward)) is None
    assert _reference_by_contract(_FakeTask(_FakeData(turns={"a": 1}), reward)) is None


def test_the_recognised_name_still_wins_when_present() -> None:
    """Contract discovery is a fallback, not a replacement: the cheap, conventional path
    runs first so nothing about existing tasksets changes."""
    from bohrin.adapters.verifiers_v1 import _first_reference

    assert _first_reference(_FakeData(answer="70", word="alpha")) == "70"
