"""The finding record: its ID is stable, its evidence rules hold, and its published schema agrees.

A record that claims more than its evidence supports must not exist, so every rule is tested by a
record that breaks exactly that rule, and the published JSON Schema is held to refuse the same
records the code refuses. If the two ever disagreed, a third party validating against the schema
would accept findings Bohrin itself would not make.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from bohrin.evidence import (
    SCHEMA,
    DifferentiatingInput,
    DifferentiatingObservation,
    Finding,
    Reproduction,
    Run,
    Scored,
    Submission,
    finding_id,
    finding_schema,
    normalise_finding_id,
)
from bohrin.ir.task import Ground, Shape, Source, Workspace

_EMPTIED = Submission.of(Source("def solve(items):\n    pass\n"))
_DIGEST = "sha256:" + "ab" * 32
_VALIDATOR = Draft202012Validator(finding_schema())


def _proven(**changes: Any) -> Finding:
    base = Finding(
        id=finding_id("bohrin/empty-implementation@1", "task-1", "grader-digest", _EMPTIED),
        weakness="BGW-101",
        probe="bohrin/empty-implementation@1",
        level="proven",
        task_id="task-1",
        shape=Shape.PROGRAM,
        battery=2,
        submission=_EMPTIED,
        ground=Ground.STRUCTURAL,
        verdict=Scored(reward=1.0, passed=True),
        baseline_passed=True,
        reproduce=Reproduction(script="reproduce.py", sha256=_DIGEST),
        run=Run(tool="example", tool_version="1.0", conditions={"timeout_s": 600, "egress": "blocked"}),
        fix="Check return values against known outputs on inputs the submission cannot see.",
    )
    return replace(base, **changes)


def _observation(presumed: tuple[bool, ...] = (True, True, True), **changes: Any) -> DifferentiatingObservation:
    fields: dict[str, Any] = {
        "requirement": "Configure a swap file that the system uses.",
        "observation": "swapon --show",
        "reference_passed": True,
        "presumed_correct_passed": presumed,
        "submission_passed": False,
    }
    fields.update(changes)
    return DifferentiatingObservation(**fields)


# --------------------------------------------------------------------------- finding IDs


def test_the_id_is_pinned_so_it_can_never_change_silently() -> None:
    """A published ID is permanent. Changing how it is derived would re-number every finding."""
    assert finding_id("bohrin/empty-implementation@1", "task-1", "grader-digest", _EMPTIED) == "BF-130XFM28BK"


def test_the_same_inputs_give_the_same_id_and_any_change_gives_another() -> None:
    args: tuple[str, str, str, Submission] = ("bohrin/empty-implementation@1", "task-1", "g", _EMPTIED)
    ids = {
        finding_id(*args),
        finding_id("bohrin/empty-implementation@2", "task-1", "g", _EMPTIED),
        finding_id("bohrin/empty-implementation@1", "task-2", "g", _EMPTIED),
        finding_id("bohrin/empty-implementation@1", "task-1", "h", _EMPTIED),
        finding_id("bohrin/empty-implementation@1", "task-1", "g", Submission.of(Source("pass"))),
    }
    assert finding_id(*args) == finding_id(*args)
    assert len(ids) == 5


def test_ids_use_only_crockford_symbols() -> None:
    for n in range(200):
        body = finding_id("bohrin/x@1", f"task-{n}", "g", _EMPTIED)[3:]
        assert len(body) == 10 and not set(body) & set("ILOU")


@pytest.mark.parametrize("typed", ["bf-130xfm28bk", "BF-130X-FM28-BK", " BF-130XFM28BK "])
def test_an_id_is_read_the_way_people_type_it(typed: str) -> None:
    assert normalise_finding_id(typed) == "BF-130XFM28BK"


def test_misreadable_letters_are_read_as_the_digits_they_resemble() -> None:
    assert normalise_finding_id("BF-OOOOOIIILL") == "BF-0000011111"


@pytest.mark.parametrize("typed", ["130XFM28BK", "BF-130XFM28B", "BF-130XFM28BU", "BVR-2026-00042"])
def test_what_is_not_an_id_is_refused(typed: str) -> None:
    with pytest.raises(ValueError):
        normalise_finding_id(typed)


# --------------------------------------------------------------------------- submissions


def test_a_record_carries_digests_never_the_submission() -> None:
    workspace = Workspace({"{test_root}/conftest.py": "# hook\n", "tests/test_a.py": None}, parameters=("test_root",))
    record = Submission.of(workspace).to_json()

    assert record["files"]["tests/test_a.py"] is None, "a deletion stays visible"
    assert record["files"]["{test_root}/conftest.py"].startswith("sha256:")
    assert "# hook" not in str(record)


# --------------------------------------------------------------------------- the rules of evidence


def test_a_complete_proven_finding_is_accepted() -> None:
    assert _proven().level == "proven"


@pytest.mark.parametrize(
    ("rule", "changes"),
    [
        ("I1: no ground", {"ground": None}),
        ("no submission", {"submission": None}),
        ("no verdict", {"verdict": None}),
        ("the grader did not pay", {"verdict": Scored(reward=0.0, passed=False)}),
        ("I4: baseline failed", {"baseline_passed": False}),
        ("I4: baseline unknown", {"baseline_passed": None}),
        ("I7: no reproduction", {"reproduce": None}),
        ("I8: differential with no differentiating evidence", {"ground": Ground.DIFFERENTIAL}),
        ("malformed ID", {"id": "BF-123"}),
        ("malformed weakness", {"weakness": "CWE-79"}),
        ("malformed probe", {"probe": "empty-implementation"}),
        ("unknown level", {"level": "confirmed"}),
    ],
)
def test_a_finding_claiming_more_than_its_evidence_is_refused(rule: str, changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _proven(**changes)


def test_a_differential_ground_is_proven_by_a_differentiating_input() -> None:
    evidence = DifferentiatingInput(input="[1, 2]", reference_output="3", submission_output="None")
    assert _proven(ground=Ground.DIFFERENTIAL, differentiating_input=evidence).ground is Ground.DIFFERENTIAL


def test_a_differentiating_input_must_differentiate() -> None:
    with pytest.raises(ValueError):
        DifferentiatingInput(input="[1, 2]", reference_output="3", submission_output="3")


def test_a_sound_observation_proves_an_experimental_finding() -> None:
    finding = _proven(
        level="proven-experimental", ground=Ground.DIFFERENTIAL, differentiating_observation=_observation()
    )
    assert finding.differentiating_observation is not None and finding.differentiating_observation.proves


@pytest.mark.parametrize(
    ("rule", "observation"),
    [
        ("I12: only two presumed-correct end states", _observation(presumed=(True, True))),
        ("I12: one presumed-correct end state fails it", _observation(presumed=(True, True, False))),
        ("I12: the reference fails it", _observation(reference_passed=False)),
        ("the submission passes it", _observation(submission_passed=True)),
    ],
)
def test_an_observation_that_may_be_too_narrow_proves_nothing(
    rule: str, observation: DifferentiatingObservation
) -> None:
    assert not observation.proves, rule
    with pytest.raises(ValueError):
        _proven(level="proven-experimental", ground=Ground.DIFFERENTIAL, differentiating_observation=observation)


def test_a_finding_proven_by_observation_is_never_plain_proven() -> None:
    with pytest.raises(ValueError, match="proven-experimental"):
        _proven(ground=Ground.DIFFERENTIAL, differentiating_observation=_observation())


@pytest.mark.parametrize("level", ["lead", "excluded"])
def test_a_lead_or_excluded_result_says_why(level: str) -> None:
    with pytest.raises(ValueError):
        _proven(level=level)
    assert _proven(level=level, reason="the reproduction script did not re-create it").level == level


def test_an_observation_needs_no_verdict() -> None:
    fact = Finding(
        id="BF-0000000000",
        weakness="BGW-109",
        probe="bohrin/assertions-removed@1",
        level="observation",
        task_id="HEAD~1..HEAD",
        shape=Shape.HISTORY,
        battery=2,
    )
    assert fact.verdict is None


# --------------------------------------------------------------------------- the published schema


def test_the_schema_is_valid_and_published_at_its_id() -> None:
    Draft202012Validator.check_schema(finding_schema())
    assert finding_schema()["$id"] == SCHEMA


_VALID: list[Callable[[], Finding]] = [
    _proven,
    lambda: _proven(
        ground=Ground.DIFFERENTIAL,
        differentiating_input=DifferentiatingInput(input="[1]", reference_output="1", submission_output="None"),
    ),
    lambda: _proven(
        level="proven-experimental", ground=Ground.DIFFERENTIAL, differentiating_observation=_observation()
    ),
    lambda: _proven(level="lead", reason="accepted; could not establish it is wrong", reproduce=None),
    lambda: _proven(
        submission=Submission.of(Workspace({"tests/test_a.py": None}, commands=("true",))), shape=Shape.WORKSPACE
    ),
]


@pytest.mark.parametrize("make", _VALID)
def test_every_record_the_code_makes_conforms_to_the_schema_and_reads_back(make: Callable[[], Finding]) -> None:
    finding = make()
    data = finding.to_json()

    assert list(_VALIDATOR.iter_errors(data)) == []
    assert Finding.from_json(data) == finding


def _drop(key: str) -> Callable[[dict[str, Any]], None]:
    return lambda data: data.pop(key)


def _set(path: tuple[str, ...], value: Any) -> Callable[[dict[str, Any]], None]:
    def apply(data: dict[str, Any]) -> None:
        target = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return apply


_OBSERVED = _proven(level="proven-experimental", ground=Ground.DIFFERENTIAL, differentiating_observation=_observation())


@pytest.mark.parametrize(
    ("rule", "base", "breakage"),
    [
        ("I1: no ground", _proven(), _drop("ground")),
        ("I7: no reproduction", _proven(), _drop("reproduce")),
        ("the grader did not pay", _proven(), _set(("verdict", "passed"), False)),
        ("I4: baseline failed", _proven(), _set(("baseline", "passed"), False)),
        ("I8: differential with no evidence", _proven(), _set(("ground",), "differential")),
        (
            "I12: two presumed-correct",
            _OBSERVED,
            _set(("differentiating_observation", "presumed_correct_passed"), [True] * 2),
        ),
        (
            "I12: one presumed-correct fails",
            _OBSERVED,
            _set(("differentiating_observation", "presumed_correct_passed"), [True, False, True]),
        ),
        ("observation proven as plain proven", _OBSERVED, _set(("level",), "proven")),
        ("a lead with no reason", _proven(level="lead", reason="x"), _drop("reason")),
        ("malformed ID", _proven(), _set(("id",), "BF-7K3Q9D2M1U")),
        ("unknown field", _proven(), _set(("confidence",), 0.9)),
        ("unknown nested field", _proven(), _set(("verdict", "confidence"), 0.9)),
    ],
)
def test_the_schema_refuses_exactly_what_the_code_refuses(
    rule: str, base: Finding, breakage: Callable[[dict[str, Any]], None]
) -> None:
    data = copy.deepcopy(base.to_json())
    breakage(data)

    assert list(_VALIDATOR.iter_errors(data)), f"the schema accepted: {rule}"
    with pytest.raises((ValueError, TypeError)):
        Finding.from_json(data)
