"""The legacy verifiers adapter — the `load_environment` API.

The published ecosystem is still on this API, so these tests guard the path that most real
environments take. Two behaviours here are re-implementations of private upstream
behaviour and are pinned deliberately: how a rubric group exposes its weighted reward
functions, and how upstream reports a reward function that raised. If either changes, the
failure must surface here rather than as silently wrong audits in front of a customer.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest

from bohrin.adapters._package import distribution_name
from bohrin.adapters.verifiers_legacy import (
    _VERIFIERS_LOGGER,
    VerifiersLegacyAdapter,
    _defines_entry,
    _LegacySource,
    _prompt_text,
    _reference,
    _requires_runtime,
    _scoring_funcs,
)
from bohrin.ir.task import Candidate, Provenance, Task

# --------------------------------------------------------------------------- helpers


def _env_dir(tmp_path: Path, *, name: str = "demo_env", module: str = "", taskset: bool = False) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "pyproject.toml").write_text(f'[project]\nname = "{name}"\nversion = "0.1.0"\n', encoding="utf-8")
    (root / f"{name}.py").write_text(module or "def load_environment(**kwargs):\n    return None\n", encoding="utf-8")
    if taskset:
        (root / "taskset.py").write_text("class T: pass\n", encoding="utf-8")
    return root


class _Rubric:
    """Stands in for a rubric group: children hold the funcs, the parent holds none."""

    def __init__(self, funcs: list[Any], weights: list[float], children: list[_Rubric] | None = None) -> None:
        self.funcs = funcs
        self.weights = weights
        self.rubrics = children or []


# --------------------------------------------------------------------------- detection


def test_a_published_environment_is_claimed(tmp_path: Path) -> None:
    assert VerifiersLegacyAdapter().detect(_env_dir(tmp_path)) == pytest.approx(0.9)


def test_a_migrated_taskset_is_left_to_the_v1_adapter(tmp_path: Path) -> None:
    """An environment that has migrated must be read through the API it migrated to."""
    assert VerifiersLegacyAdapter().detect(_env_dir(tmp_path, taskset=True)) == 0.0


def test_a_directory_of_junk_is_not_claimed(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("load_environment", encoding="utf-8")
    assert VerifiersLegacyAdapter().detect(tmp_path) == 0.0


def test_the_entry_point_is_parsed_and_not_pattern_matched(tmp_path: Path) -> None:
    """A mention in a comment, a docstring or an import is not a definition.

    Detection that fires on a mention claims paths this adapter cannot load, and the user
    is then told the environment is broken rather than that it is unsupported.
    """
    mentions = (
        "# load_environment lives elsewhere\n",
        '"""Call load_environment to build it."""\n',
        "from somewhere import load_environment\n",
        "load_environment = None\n",
    )
    for index, source in enumerate(mentions):
        module = tmp_path / f"m{index}.py"
        module.write_text(source, encoding="utf-8")
        assert _defines_entry(module) is False, source

    real = tmp_path / "real.py"
    real.write_text("def load_environment():\n    return 1\n", encoding="utf-8")
    assert _defines_entry(real) is True


def test_an_unparseable_module_is_not_a_match_and_never_an_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.py"
    broken.write_text("def load_environment(:\n", encoding="utf-8")
    assert _defines_entry(broken) is False


def test_the_distribution_name_comes_from_pyproject_and_is_never_guessed(tmp_path: Path) -> None:
    root = _env_dir(tmp_path, name="my_env")
    assert distribution_name(root) == "my_env"
    (root / "pyproject.toml").write_text("[project]\nversion = '1'\n", encoding="utf-8")
    assert distribution_name(root) is None


# --------------------------------------------------------------------------- the rubric


def test_a_rubric_groups_children_carry_the_reward_functions() -> None:
    def a() -> float:
        return 1.0

    def b() -> float:
        return 1.0

    group = _Rubric([], [], [_Rubric([a], [1.0]), _Rubric([b], [0.5])])
    assert [(fn.__name__, w) for fn, w in _scoring_funcs(group)] == [("a", 1.0), ("b", 0.5)]


def test_a_zero_weight_entry_is_a_metric_not_a_reward() -> None:
    """Counting a metric as attainable reward would put full marks out of reach.

    Upstream records metrics such as ``num_turns`` alongside the score with weight zero. If
    they counted, no candidate could ever reach the attainable total and every submission —
    including the known-good answer — would read as rejected.
    """

    def scored() -> float:
        return 1.0

    def metric() -> float:
        return 1.0

    assert [fn.__name__ for fn, _ in _scoring_funcs(_Rubric([scored, metric], [1.0, 0.0]))] == ["scored"]


def test_a_reward_function_needing_a_live_rollout_is_recognised() -> None:
    def offline(completion: str, answer: str) -> float:
        return 0.0

    def judged(completion: str, client: Any) -> float:
        return 0.0

    def defaulted(completion: str, client: Any = None) -> float:
        return 0.0

    assert _requires_runtime(offline) is False
    assert _requires_runtime(judged) is True
    # A defaulted parameter can still be called offline with None.
    assert _requires_runtime(defaulted) is False


# --------------------------------------------------------------------------- rows


def test_an_empty_answer_is_not_a_reference() -> None:
    """Rows in this API set ``answer`` to "" when grading is driven from ``info``.

    Treating that as a known-good answer would let a differential operator report that the
    verifier accepted "nothing" as correct.
    """
    assert _reference({"answer": ""}) is None
    assert _reference({"answer": "   "}) is None
    assert _reference({"answer": "42"}) == "42"
    assert _reference({"solution": "42"}) == "42"
    assert _reference({}) is None


def test_the_prompt_is_readable_whether_it_is_a_string_or_a_message_list() -> None:
    assert _prompt_text({"question": "What is 2+2?"}) == "What is 2+2?"
    assert _prompt_text({"prompt": [{"role": "user", "content": "hi"}]}) == "hi"
    assert _prompt_text({"question": "  ", "prompt": [{"role": "user", "content": "hi"}]}) == "hi"
    assert _prompt_text({}) == ""


# --------------------------------------------------------------------------- scoring


def _source_with(rubric: Any, *, attainable: float) -> _LegacySource:
    """A source with the loading skipped: these tests are about scoring, not loading."""
    source = object.__new__(_LegacySource)
    source._rubric = rubric
    source._scoring = []
    source._attainable = attainable
    source._by_id = {"0": {"answer": "", "info": {}, "prompt": [], "example_id": 0}}
    return source


def _task() -> Task:
    return Task(id="0", prompt="p", reference=None, reward_fns=("r",), metadata={})


def _candidate() -> Candidate:
    return Candidate(payload="x", provenance=Provenance(operator="t", base="constant", detail="d"))


class _ScoringRubric:
    """Scores through the state it is handed, the way upstream does."""

    def __init__(self, reward: float, *, errors: int = 0) -> None:
        self._reward = reward
        self._errors = errors

    async def score_rollout(self, state: Any) -> None:
        for index in range(self._errors):
            logging.getLogger(_VERIFIERS_LOGGER).error(f"Error calling reward function f{index}: 'is_solved'")
        state["reward"] = self._reward
        state["metrics"] = {"r": self._reward}


def test_a_score_is_read_back_from_the_state_upstream_mutates() -> None:
    source = _source_with(_ScoringRubric(1.0), attainable=1.0)
    verdict = asyncio.run(source.score(_task(), _candidate()))
    assert verdict.reward == 1.0
    assert verdict.passed is True
    assert verdict.per_fn == {"r": 1.0}


def test_full_marks_is_acceptance_and_a_partial_score_is_not() -> None:
    source = _source_with(_ScoringRubric(0.5), attainable=1.0)
    assert asyncio.run(source.score(_task(), _candidate())).passed is False


def test_a_rubric_that_raised_is_refused_rather_than_scored_zero() -> None:
    """The bug this guards is the one that manufactures findings in both directions.

    Upstream catches a raising reward function, logs it, and records zero for it. The total
    that comes back is a partial rubric wearing a complete rubric's number: nothing can
    reach full marks, so no exploit is ever reported, and the known-good answer fails too,
    which reads as a verifier that rejects its own ground truth. Neither is true.
    """
    source = _source_with(_ScoringRubric(0.04, errors=4), attainable=2.1)
    with pytest.raises(RuntimeError, match="partially evaluated"):
        asyncio.run(source.score(_task(), _candidate()))


def test_the_captured_logger_is_restored_and_not_left_silenced() -> None:
    logger = logging.getLogger(_VERIFIERS_LOGGER)
    before = logger.propagate
    source = _source_with(_ScoringRubric(0.0, errors=1), attainable=1.0)
    with pytest.raises(RuntimeError):
        asyncio.run(source.score(_task(), _candidate()))
    assert logger.propagate is before
    assert not [h for h in logger.handlers if type(h).__name__ == "_ErrorCapture"]


def test_a_task_needing_a_live_rollout_is_refused_before_it_is_scored() -> None:
    source = _source_with(_ScoringRubric(1.0), attainable=1.0)
    task = Task(id="0", prompt="p", reward_fns=("j",), metadata={"requires_runtime": ("j",)})
    with pytest.raises(RuntimeError, match="live rollout"):
        asyncio.run(source.score(task, _candidate()))


def test_a_task_from_another_source_is_rejected() -> None:
    source = _source_with(_ScoringRubric(1.0), attainable=1.0)
    with pytest.raises(KeyError):
        asyncio.run(source.score(Task(id="nope", prompt="p"), _candidate()))
