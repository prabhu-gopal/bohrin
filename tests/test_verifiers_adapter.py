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
