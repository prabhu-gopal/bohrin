"""The Inspect adapter, tested against the real library.

Skipped when the extra is absent, but not optional in CI: the adapter intercepts private
upstream functions to keep a scorer from reaching a model or a sandbox, and if upstream
moves them the failure must surface here rather than as a false accusation in a report.

Each fixture is a real ``@task`` file written to a temporary directory and read through the
adapter exactly as ``bohrin audit <file>`` would read it. Task and file names are unique per
test because Inspect's registry is process-wide.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from bohrin.adapters.base import ScoringRefused, TaskSource
from bohrin.adapters.inspect_tasks import InspectAdapter
from bohrin.adapters.registry import detect, discover
from bohrin.config import ScanConfig
from bohrin.execute.runner import score_many
from bohrin.ir.evidence import Exploit, GroundTruthRejected, HarnessDisruption
from bohrin.ir.task import Candidate, Provenance
from bohrin.probes.base import ProbeStatus
from bohrin.probes.ground_truth_rejected import GroundTruthRejectedProbe
from bohrin.probes.weak_oracle import WeakOracleProbe

pytest.importorskip("inspect_ai", reason="the inspect extra is not installed")

CONFIG = ScanConfig(unsafe_local=True)

_HEADER = """
from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import get_model
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox
"""

_SAMPLES = (
    'MemoryDataset([Sample(id="capital", input="What is the capital of Australia?", target="Canberra"), '
    'Sample(id="ocean", input="What is the largest ocean?", target="Pacific")])'
)


def _write(tmp_path: Path, stem: str, body: str) -> Path:
    path = tmp_path / f"{stem}.py"
    path.write_text(_HEADER + textwrap.dedent(body), encoding="utf-8")
    return path


def _load(path: Path, config: ScanConfig = CONFIG) -> TaskSource:
    return InspectAdapter().load(path, config)


def _cand(payload: str) -> Candidate:
    return Candidate(payload=payload, provenance=Provenance(operator="test", base="constant", detail="test"))


# --------------------------------------------------------------------------- discovery


def test_the_inspect_adapter_is_registered() -> None:
    assert "inspect" in {adapter.name for adapter in discover()}


def test_a_task_file_is_detected_from_its_text(tmp_path: Path) -> None:
    path = _write(tmp_path, "detect_me", "@task\ndef detect_me():\n    return Task(dataset=[])\n")
    other = tmp_path / "plain.py"
    other.write_text("print('not an evaluation')\n", encoding="utf-8")

    assert detect(path).name == "inspect"
    assert InspectAdapter().detect(tmp_path) > 0.5
    assert InspectAdapter().detect(other) == 0.0


def test_one_bohrin_task_per_sample_with_the_target_as_reference(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "shape_file",
        f"""
        @scorer(metrics=[accuracy()])
        def exact_text():
            async def score(state: TaskState, target: Target) -> Score:
                return Score(value=CORRECT if state.output.completion.strip() == target.text else INCORRECT)
            return score

        @task
        def shape_task():
            return Task(dataset={_SAMPLES}, scorer=exact_text())
        """,
    )

    tasks = list(_load(path).tasks())

    assert [t.id for t in tasks] == ["shape_task/capital", "shape_task/ocean"]
    assert tasks[0].reference == "Canberra"
    assert tasks[0].prompt == "What is the capital of Australia?"
    assert tasks[0].reward_fns == ("exact_text",)
    assert tasks[0].metadata["offline_scoreable"] is True


async def test_a_target_with_several_valid_answers_declares_none(tmp_path: Path) -> None:
    """Every item of a list target is correct, so none of them may serve as "the" answer.

    Measured before this guard: an ``inspect_evals/drop`` sample with target ``['2', '1']`` was
    reported as accepting the wrong answer ``1``.
    """
    path = _write(
        tmp_path,
        "multi_target_file",
        """
        from inspect_ai.scorer import includes

        @task
        def multi_target_task():
            return Task(
                dataset=[Sample(id="count", input="How many?", target=["2", "1"]),
                         Sample(id="same", input="Capital?", target=["Canberra", "Canberra "])],
                scorer=includes(),
            )
        """,
    )
    source = _load(path)
    tasks = {t.id: t for t in source.tasks()}

    assert tasks["multi_target_task/count"].reference is None
    assert tasks["multi_target_task/same"].reference == "Canberra", "one distinct answer is still an answer"
    result = await WeakOracleProbe().run(source, CONFIG)
    assert not [
        f
        for f in result.findings
        if isinstance(f, Exploit) and f.task_id == "multi_target_task/count" and f.candidate.payload == "1"
    ]


# --------------------------------------------------------------------------- scoring


async def test_a_scorer_that_pays_for_a_wrong_answer_is_found(tmp_path: Path) -> None:
    """The shape of a real defect: a substring check that accepts a denial of the answer."""
    path = _write(
        tmp_path,
        "lenient_file",
        f"""
        @scorer(metrics=[accuracy()])
        def contains_answer():
            async def score(state: TaskState, target: Target) -> Score:
                return Score(value=CORRECT if target.text.lower() in state.output.completion.lower() else INCORRECT)
            return score

        @task
        def lenient_task():
            return Task(dataset={_SAMPLES}, scorer=contains_answer())
        """,
    )

    result = await WeakOracleProbe().run(_load(path), CONFIG)

    exploits = [f for f in result.findings if isinstance(f, Exploit)]
    assert {e.task_id for e in exploits} == {"lenient_task/capital", "lenient_task/ocean"}
    assert any("not" in e.candidate.payload.lower() for e in exploits)


async def test_a_strict_scorer_is_not_accused(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "strict_file",
        f"""
        @scorer(metrics=[accuracy()])
        def exact_only():
            async def score(state: TaskState, target: Target) -> Score:
                return Score(value=CORRECT if state.output.completion.strip() == target.text else INCORRECT)
            return score

        @task
        def strict_task():
            return Task(dataset={_SAMPLES}, scorer=exact_only())
        """,
    )

    result = await WeakOracleProbe().run(_load(path), CONFIG)

    assert result.findings == ()


async def test_a_real_crash_is_still_reported_with_the_scorers_own_exception(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "crash_file",
        f"""
        @scorer(metrics=[accuracy()])
        def crashes_on_empty():
            async def score(state: TaskState, target: Target) -> Score:
                first_word = state.output.completion.split()[0]
                return Score(value=CORRECT if first_word == target.text else INCORRECT)
            return score

        @task
        def crash_task():
            return Task(dataset={_SAMPLES}, scorer=crashes_on_empty())
        """,
    )

    result = await WeakOracleProbe().run(_load(path), CONFIG)

    crashes = [f for f in result.findings if isinstance(f, HarnessDisruption)]
    assert crashes, "an IndexError on an empty reply is the grader's defect"
    assert all("IndexError" in c.error for c in crashes)


async def test_dict_score_values_pass_only_when_every_value_is_full_marks(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "dict_file",
        f"""
        @scorer(metrics=[accuracy()])
        def two_parts():
            async def score(state: TaskState, target: Target) -> Score:
                reply = state.output.completion
                return Score(value={{"mentions": CORRECT if target.text in reply else INCORRECT,
                                     "short": CORRECT if len(reply) < 10 else INCORRECT}})
            return score

        @task
        def dict_task():
            return Task(dataset={_SAMPLES}, scorer=two_parts())
        """,
    )
    source = _load(path)
    task = next(iter(source.tasks()))

    exact = await source.score(task, _cand("Canberra"))
    long = await source.score(task, _cand("It is Canberra, of course."))

    assert exact.passed and exact.reward == 1.0
    assert not long.passed and long.reward == 0.5


# --------------------------------------------------------------------------- refusals


def test_model_graded_and_sandboxed_tasks_are_refused_before_scoring(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "refused_file",
        f"""
        from inspect_ai.scorer import model_graded_qa, includes

        @task
        def judged_task():
            return Task(dataset={_SAMPLES}, scorer=model_graded_qa())

        @task
        def sandboxed_task():
            return Task(dataset={_SAMPLES}, scorer=includes(), sandbox="docker")
        """,
    )

    tasks = {t.id: t for t in _load(path).tasks()}

    assert "calls a model" in tasks["judged_task/capital"].metadata["requires_runtime"][0]
    assert "sandbox" in tasks["sandboxed_task/capital"].metadata["requires_runtime"][0]
    assert all(not t.metadata["offline_scoreable"] for t in tasks.values())


async def test_a_refused_task_is_never_scored_as_clean(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "judged_only_file",
        f"""
        from inspect_ai.scorer import model_graded_fact

        @task
        def judged_only_task():
            return Task(dataset={_SAMPLES}, scorer=model_graded_fact())
        """,
    )

    result = await WeakOracleProbe().run(_load(path), CONFIG)

    assert result.findings == ()
    assert result.status is not ProbeStatus.OK, "nothing was measured, so nothing may read as clean"
    assert result.sub_score is None
    assert "calls a model" in str(result.detail)


async def test_a_judge_fallback_is_declined_not_reported_as_a_crash(tmp_path: Path) -> None:
    """The false accusation this adapter exists to prevent.

    The scorer matches exactly, rejects most replies outright, and asks a model only about
    replies that mention "not". Other submissions to the task score normally, so a submission
    that reaches the model call would read as "the grader crashes on this input" -- a defect
    Bohrin caused. It must be declined instead.
    """
    path = _write(
        tmp_path,
        "fallback_file",
        f"""
        @scorer(metrics=[accuracy()])
        def exact_then_judge():
            async def score(state: TaskState, target: Target) -> Score:
                reply = state.output.completion.strip()
                if reply == target.text:
                    return Score(value=CORRECT)
                if " not " not in f" {{reply.lower()}} ":
                    return Score(value=INCORRECT)
                judge = get_model()
                verdict = await judge.generate("Is this answer correct?")
                return Score(value=CORRECT if "yes" in verdict.completion.lower() else INCORRECT)
            return score

        @task
        def fallback_task():
            return Task(dataset={_SAMPLES}, scorer=exact_then_judge())
        """,
    )

    result = await WeakOracleProbe().run(_load(path), CONFIG)

    assert not [f for f in result.findings if isinstance(f, HarnessDisruption)]
    assert not [f for f in result.findings if isinstance(f, Exploit)]
    assert result.detail["errors"] > 0, "the counterweight: the model call was reached and declined"


async def test_a_scorer_that_swallows_the_refusal_is_declined(tmp_path: Path) -> None:
    """A scorer that catches the failed model call and returns INCORRECT would otherwise make
    a correct answer look rejected -- a false "refuses its own answer" finding."""
    path = _write(
        tmp_path,
        "swallow_file",
        f"""
        @scorer(metrics=[accuracy()])
        def always_asks():
            async def score(state: TaskState, target: Target) -> Score:
                try:
                    judge = get_model()
                    verdict = await judge.generate("Is this answer correct?")
                except Exception:
                    return Score(value=INCORRECT)
                return Score(value=CORRECT if "yes" in verdict.completion.lower() else INCORRECT)
            return score

        @task
        def swallow_task():
            return Task(dataset={_SAMPLES}, scorer=always_asks())
        """,
    )
    source = _load(path)
    task = next(iter(source.tasks()))

    with pytest.raises(ScoringRefused):
        await source.score(task, _cand("Canberra"))

    result = await GroundTruthRejectedProbe().run(source, CONFIG)
    assert not [f for f in result.findings if isinstance(f, GroundTruthRejected)]


async def test_a_sandbox_call_inside_a_scorer_is_declined(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "sandbox_call_file",
        f"""
        @scorer(metrics=[accuracy()])
        def runs_a_command():
            async def score(state: TaskState, target: Target) -> Score:
                result = await sandbox().exec(["cat", "answer.txt"])
                return Score(value=CORRECT if result.stdout.strip() == target.text else INCORRECT)
            return score

        @task
        def sandbox_call_task():
            return Task(dataset={_SAMPLES}, scorer=runs_a_command())
        """,
    )
    source = _load(path)
    task = next(iter(source.tasks()))

    outcomes = await score_many(source, [(task, _cand("Canberra")), (task, _cand(""))], CONFIG)

    assert all(out.refused for out in outcomes)


def test_the_guards_are_invisible_outside_a_bohrin_score_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Installing the guards must not change what Inspect does for anyone else."""
    path = _write(
        tmp_path, "guard_file", '@task\ndef guard_task():\n    return Task(dataset=[Sample(input="q", target="a")])\n'
    )
    _load(path)  # installs the guards
    monkeypatch.delenv("INSPECT_EVAL_MODEL", raising=False)

    import inspect_ai.model

    with pytest.raises(ValueError, match="No model specified"):
        inspect_ai.model.get_model()


# --------------------------------------------------------------------------- selection


def test_max_tasks_and_a_sample_seed_bound_the_samples(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "bounded_file",
        """
        from inspect_ai.scorer import exact

        @task
        def bounded_task():
            return Task(dataset=[Sample(id=str(i), input=f"q{i}", target=str(i)) for i in range(10)], scorer=exact())
        """,
    )

    prefix = _load(path, ScanConfig(unsafe_local=True, max_tasks=3))
    sampled = _load(path, ScanConfig(unsafe_local=True, max_tasks=3, sample_seed=7))

    assert [t.id for t in prefix.tasks()] == ["bounded_task/0", "bounded_task/1", "bounded_task/2"]
    assert len(list(sampled.tasks())) == 3
    assert getattr(sampled, "selection_seed", None) == 7
    assert getattr(prefix, "corpus_total", None) == 10


# --------------------------------------------------------------------------- upstream pins


def test_the_private_upstream_details_the_guards_rely_on_still_exist() -> None:
    import inspect_ai._util.registry as registry
    import inspect_ai.model._model as model_mod
    import inspect_ai.util._sandbox.context as sandbox_mod

    assert callable(model_mod.get_model)
    assert callable(model_mod.active_model)
    assert isinstance(model_mod.Model, type)
    assert callable(sandbox_mod.sandbox)
    assert callable(registry.is_registry_object)
    assert callable(registry.registry_unqualified_name)


def test_a_file_whose_task_needs_arguments_fails_to_load_clearly(tmp_path: Path) -> None:
    from bohrin.adapters.base import TasksetLoadError

    path = _write(
        tmp_path,
        "args_file",
        """
        @task
        def needs_args_task(subset: str):
            return Task(dataset=[])
        """,
    )

    with pytest.raises(TasksetLoadError, match="needs_args_task"):
        _load(path)
