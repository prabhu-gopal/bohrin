"""The conformance suite: its fixtures are what they claim, and the check of a tool is exact.

Three things are held here. The index and the grader files are one set. Each fixture is what it
says, shown the way NIST's Juliet suite shows its good and bad cases: every correct grader accepts
the reference and every certified rewriting of it, and each grader with a defect shows exactly
that defect on a demonstration its correct partner gets right. And the check gives a level only to
a tool that flags every defect and accuses no correct grader.

The tests run the fixture graders on fixture-local programs; the library never does.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from _fixtures import REFERENCE, task
from _parity import disagreements
from bohrin.cli import CANNOT_RUN, CLEAN, FINDINGS, main
from bohrin.conformance import (
    CONFORMANCE_RESULTS_SCHEMA,
    Fixture,
    Results,
    check,
    conformance_results_schema,
    read_results,
    render,
    suite,
)
from bohrin.ir.task import Shape, Source
from bohrin.mutate.battery import battery
from bohrin.relations import positive_controls
from bohrin.spec.probes import probe_for, weakness_of
from bohrin.spec.weaknesses import weakness_list

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "conformance" / "bcl-1"
SUITE = suite()

# --------------------------------------------------------------------------- one set


def test_the_index_and_the_grader_files_are_one_set() -> None:
    assert {f.file for f in SUITE.fixtures} == {p.name for p in FIXTURES.glob("*.py")}


def test_each_checked_weakness_has_exactly_one_correct_and_one_defective_grader() -> None:
    for weakness in SUITE.covered:
        pair = sorted(f.defect for f in SUITE.fixtures if f.weakness == weakness)
        assert pair == [False, True], weakness
    assert {f.weakness for f in SUITE.fixtures} == set(SUITE.covered), "no fixture outside the covered set"


def test_every_fixture_names_a_live_weakness_of_its_shape() -> None:
    classes = {w.id: w for w in weakness_list().weaknesses}
    assert set(SUITE.weaknesses) <= set(classes) and set(SUITE.pending) <= set(SUITE.weaknesses)
    for fixture in SUITE.fixtures:
        weakness = classes[fixture.weakness]
        assert weakness.status == "active"
        assert fixture.shape in SUITE.shapes and fixture.shape in weakness.shapes, fixture.id


def test_fixture_ids_and_file_names_agree() -> None:
    ids = [f.id for f in SUITE.fixtures]
    assert len(ids) == len(set(ids))
    for fixture in SUITE.fixtures:
        _, slug, kind = fixture.id.split("/")
        assert fixture.file == f"{slug}-{kind}.py"
        assert (kind == "defect") is fixture.defect


def test_each_grader_says_what_it_is_in_its_first_line() -> None:
    for fixture in SUITE.fixtures:
        first = (FIXTURES / fixture.file).read_text(encoding="utf-8").splitlines()[0]
        slug = fixture.id.split("/")[1]
        expected = f"with defect {fixture.weakness}" if fixture.defect else "correct"
        assert first.startswith(f'"""BCL-1 fixture: {slug}, {expected}'), fixture.id


# --------------------------------------------------------------------------- the fixtures are what they claim


def _grader(name: str) -> Callable[[str], float]:
    namespace: dict[str, Any] = {"__name__": "fixture"}
    source = (FIXTURES / name).read_text(encoding="utf-8")
    exec(compile(source, name, "exec"), namespace)
    grade: Callable[[str], float] = namespace["grade"]
    return grade


def _pair(slug: str) -> tuple[Callable[[str], float], Callable[[str], float]]:
    return _grader(f"{slug}-correct.py"), _grader(f"{slug}-defect.py")


_PROGRAM_SLUGS = [f.id.split("/")[1] for f in SUITE.fixtures if f.shape is Shape.PROGRAM and not f.defect]


@pytest.mark.parametrize("slug", _PROGRAM_SLUGS)
def test_every_correct_grader_accepts_the_reference_and_every_certified_rewriting(slug: str) -> None:
    correct, _ = _pair(slug)
    # A comment and an unusual layout, so every kind of certified rewriting has something to change.
    commented = REFERENCE.replace("total = 0", "total = (0)  # the running sum")
    controls = positive_controls(task(commented))
    assert {c.relation for c in controls} == {"oracle", "comment_free", "reformatted", "renamed_locals"}
    assert [c.relation for c in controls if correct(c.payload.text) != 1.0] == []


def test_the_correct_io_checker_accepts_the_right_output_in_any_surrounding_whitespace() -> None:
    correct, _ = _pair("lenient-checker")
    assert correct("1 2 3\n") == correct("  1 2 3 ") == 1.0


#: For each weakness, a submission on which exactly its defect shows: (slug, submission, the
#: correct grader's reward, the defective grader's reward).
_DEMONSTRATIONS = [
    ("trivial-implementation", "def solve(items):\n    return 0\n", 0.0, 1.0),
    (
        "hard-coded-outputs",
        "def solve(items):\n    return {(1, -2, 3): 4}.get(tuple(items), 0)\n",
        0.0,
        1.0,
    ),
    ("tests-too-narrow", REFERENCE.replace("total", "running"), 1.0, 0.0),
    ("lenient-checker", "3 2 1\n", 0.0, 1.0),
    ("lenient-checker", "1 2 3 4\n", 0.0, 1.0),
    ("reference-wrong", REFERENCE, 1.0, 0.0),
    ("failure-scored-as-success", "def solve(items):\n    raise NotImplementedError\n", 0.0, 1.0),
    ("exit-before-checks", "def solve(items):\n    import sys\n    sys.exit(0)\n", 0.0, 1.0),
    ("exit-before-checks", "import sys\nsys.exit(0)\n", 0.0, 1.0),
    (
        "equality-spoofing",
        "class Anything:\n    def __eq__(self, other):\n        return True\n\n"
        "    def __ne__(self, other):\n        return False\n\n\n"
        "def solve(items):\n    return Anything()\n",
        0.0,
        1.0,
    ),
]


@pytest.mark.parametrize(("slug", "submission", "correct_reward", "defect_reward"), _DEMONSTRATIONS)
def test_each_defect_shows_where_its_correct_partner_does_not(
    slug: str, submission: str, correct_reward: float, defect_reward: float
) -> None:
    correct, defective = _pair(slug)
    assert correct(submission) == correct_reward
    assert defective(submission) == defect_reward


@pytest.mark.parametrize("slug", [s for s in _PROGRAM_SLUGS if s != "reference-wrong"])
def test_a_defective_grader_has_only_its_defect_and_accepts_the_reference(slug: str) -> None:
    """Exactly one defect: on the correct solution, the defective grader agrees with its partner."""
    correct, defective = _pair(slug)
    assert correct(REFERENCE) == defective(REFERENCE) == 1.0


def _rewards(name: str) -> dict[str, float | None]:
    """What one fixture pays for each grounded submission of the battery; None where the grader died.

    A defect grader catching only ``Exception`` dies on a submission that exits, as the suite's README
    warns; a tool records that as an error, never as a pass.
    """
    grade = _grader(name)
    out: dict[str, float | None] = {}
    for candidate in battery(task(REFERENCE)).grounded:
        assert isinstance(candidate.payload, Source)
        try:
            out[candidate.provenance.operator] = grade(candidate.payload.text)
        except BaseException:
            out[candidate.provenance.operator] = None
    return out


@pytest.mark.parametrize(
    "fixture", [f for f in SUITE.fixtures if f.shape is Shape.PROGRAM and not f.defect], ids=lambda f: f.id
)
def test_the_battery_accuses_no_correct_grader_in_the_suite(fixture: Fixture) -> None:
    assert [op for op, reward in _rewards(fixture.file).items() if reward == 1.0] == [], fixture.id


def _flags(fixture: Fixture) -> set[str]:
    """What Bohrin's battery reports on a fixture: one weakness per submission it paid for, chosen by
    the manifests' attribution rules from the fixture's own verdicts on the other submissions."""
    rewards = _rewards(fixture.file)
    rejected = {probe.id for op, reward in rewards.items() if reward == 0.0 and (probe := probe_for(op))}
    flags = set()
    for op, reward in rewards.items():
        probe = probe_for(op)
        if reward == 1.0 and probe is not None:
            flags.add(weakness_of(probe, rejected))
    return flags


#: What the battery reports on each grader with a defect. The rest need what this library does not
#: run: inputs the task does not show (BGW-104, BGW-120), a second reference (BGW-124), repeats
#: (BGW-127), or output checking (BGW-123, an io grader).
_BATTERY_FINDS = {"BGW-101", "BGW-102", "BGW-103", "BGW-126"}


@pytest.mark.parametrize("fixture", [f for f in SUITE.fixtures if f.shape is Shape.PROGRAM], ids=lambda f: f.id)
def test_the_battery_reports_each_fixture_with_its_own_weakness_or_not_at_all(fixture: Fixture) -> None:
    """No correct grader flagged, and no grader with a defect flagged for another: the level's rules."""
    expected = {fixture.weakness} if fixture.defect and fixture.weakness in _BATTERY_FINDS else set()
    assert _flags(fixture) == expected, fixture.id


def test_the_wrong_reference_fixture_pays_for_the_wrong_references_mistake() -> None:
    wrong = "def solve(items):\n    return sum(items)\n"
    correct, defective = _pair("reference-wrong")
    assert (correct(wrong), defective(wrong)) == (0.0, 1.0)


def test_no_constant_can_pass_the_random_grader_by_luck() -> None:
    """If two cases expected the same value, a constant would pass whenever both were drawn, and a tool
    right to report that as a trivial implementation would be marked as misattributing."""
    for kind in ("correct", "defect"):
        namespace: dict[str, Any] = {"__name__": "fixture"}
        name = f"nondeterministic-grader-{kind}.py"
        exec(compile((FIXTURES / name).read_text(encoding="utf-8"), name, "exec"), namespace)
        expected = [value for _, value in namespace["CASES"]]
        assert len(set(expected)) == len(expected), name


def test_the_nondeterministic_grader_disagrees_with_itself_and_its_partner_never_does() -> None:
    """Right on three of five cases: two random cases pass together with probability 3/10.

    Sixty repeats all agreeing has probability 0.3**60 + 0.7**60, below 1e-9.
    """
    partly_right = "def solve(items):\n    return sum(items)\n"
    correct, defective = _pair("nondeterministic-grader")
    assert {defective(partly_right) for _ in range(60)} == {0.0, 1.0}
    assert {correct(partly_right) for _ in range(60)} == {0.0}


# --------------------------------------------------------------------------- the check


def _results(flags: Callable[[str, bool, str], list[str] | None], **top: Any) -> dict[str, Any]:
    """A results document: ``flags(fixture id, defect, weakness)`` gives the flags, or None for not run."""
    entries = []
    for fixture in SUITE.fixtures:
        flagged = flags(fixture.id, fixture.defect, fixture.weakness)
        entries.append(
            {"fixture": fixture.id, "status": "error"}
            if flagged is None
            else {"fixture": fixture.id, "status": "ran", "flagged": flagged}
        )
    return {
        "$schema": CONFORMANCE_RESULTS_SCHEMA,
        "suite": {"level": "BCL-1", "version": SUITE.version},
        "tool": {"name": "example", "version": "1.0"},
        "results": entries,
        **top,
    }


def _perfect(_: str, defect: bool, weakness: str) -> list[str]:
    return [weakness] if defect else []


def _check(document: dict[str, Any]) -> Any:
    return check(read_results(document))


def test_a_tool_that_flags_every_defect_and_nothing_else_achieves_the_level() -> None:
    report = _check(_results(_perfect))
    assert report.achieved and report.youden == 1.0
    assert (report.true_positives, report.defective, report.false_positives, report.correct) == (9, 9, 0, 9)
    assert "BCL-1 achieved" in render(report)


def test_a_tool_that_flags_everything_accuses_every_correct_grader_and_fails() -> None:
    report = _check(_results(lambda _i, _d, weakness: [weakness]))
    assert not report.achieved and report.youden == 0.0
    assert all(not o.clean for o in report.outcomes)


def test_one_false_accusation_fails_the_level_however_much_was_found() -> None:
    def one_accusation(fixture: str, defect: bool, weakness: str) -> list[str]:
        return [weakness] if defect or fixture == "bcl-1/trivial-implementation/correct" else []

    report = _check(_results(one_accusation))
    assert not report.achieved
    assert [o.weakness for o in report.outcomes if not o.passed] == ["BGW-101"]
    assert "1 false accusation" in render(report)


def test_a_defect_flagged_under_the_wrong_weakness_is_a_misattribution() -> None:
    def also(_: str, defect: bool, weakness: str) -> list[str]:
        return [weakness, "BGW-109"] if defect and weakness == "BGW-126" else _perfect(_, defect, weakness)

    report = _check(_results(also))
    (failed,) = [o for o in report.outcomes if not o.passed]
    assert failed.weakness == "BGW-126" and failed.detected and failed.misattributed == ("BGW-109",)
    assert "also flagged BGW-109" in render(report)


def test_a_defect_found_only_under_another_name_is_not_detected() -> None:
    def renamed(_: str, defect: bool, weakness: str) -> list[str]:
        return ["BGW-101"] if defect and weakness == "BGW-104" else _perfect(_, defect, weakness)

    report = _check(_results(renamed))
    (failed,) = [o for o in report.outcomes if not o.passed]
    assert failed.weakness == "BGW-104" and not failed.detected
    assert "defect not flagged" in render(report) and "1 defect missed" in render(report)


def test_a_fixture_that_did_not_run_is_never_passed() -> None:
    def errors_on_one(fixture: str, defect: bool, weakness: str) -> list[str] | None:
        return None if fixture == "bcl-1/lenient-checker/correct" else _perfect(fixture, defect, weakness)

    report = _check(_results(errors_on_one))
    (failed,) = [o for o in report.outcomes if not o.passed]
    assert failed.not_run == ("bcl-1/lenient-checker/correct",)
    assert not failed.clean, "a correct grader that was never checked is not clean"
    rendered = render(report)
    assert "correct grader flagged" in rendered and "did not run: bcl-1/lenient-checker/correct" in rendered


def test_a_fixture_missing_from_the_results_is_never_passed() -> None:
    document = _results(_perfect)
    document["results"] = [r for r in document["results"] if r["fixture"] != "bcl-1/reference-wrong/defect"]
    (failed,) = [o for o in _check(document).outcomes if not o.passed]
    assert failed.weakness == "BGW-124" and not failed.detected


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["results"].append(dict(d["results"][0])), "reported twice"),
        (lambda d: d["results"][0].update(fixture="bcl-1/no-such-weakness/correct"), "not a fixture"),
        (lambda d: d["suite"].update(version=99), "version 99"),
        (lambda d: d["suite"].update(level="BCL-2"), "no conformance suite for BCL-2"),
    ],
    ids=["a fixture twice", "an unknown fixture", "another version", "another level"],
)
def test_results_that_cannot_be_checked_are_refused(change: Callable[[dict[str, Any]], None], message: str) -> None:
    document = _results(_perfect)
    change(document)
    with pytest.raises(ValueError, match=message):
        _check(document)


def test_the_level_is_claimed_only_over_the_weaknesses_with_fixtures_and_says_so() -> None:
    report = _check(_results(_perfect))
    assert set(report.suite.pending) == {"BGW-105"}
    assert f"checked over {len(SUITE.covered)} of its {len(SUITE.weaknesses)} weaknesses" in render(report)
    assert report.to_json()["weaknesses_pending"] == ["BGW-105"]


# --------------------------------------------------------------------------- the published format


def test_the_schema_is_valid_and_published_at_its_id() -> None:
    Draft202012Validator.check_schema(conformance_results_schema())
    assert conformance_results_schema()["$id"] == CONFORMANCE_RESULTS_SCHEMA


def test_the_reader_and_its_schema_agree_on_every_single_point_breakage() -> None:
    valid = _results(_perfect)
    valid["results"][1] = {"fixture": valid["results"][1]["fixture"], "status": "skipped", "message": "not supported"}

    def accepts(record: dict[str, Any]) -> bool:
        try:
            read_results(record)
        except (ValueError, TypeError):
            return False
        return True

    assert disagreements(valid, conformance_results_schema(), accepts) == []


def test_every_generated_results_document_conforms_to_the_schema() -> None:
    validator = Draft202012Validator(conformance_results_schema())
    for flags in (_perfect, lambda _i, _d, _w: None, lambda _i, _d, w: [w]):
        assert list(validator.iter_errors(_results(flags))) == []


def test_flagged_is_required_exactly_when_the_fixture_ran() -> None:
    for entry in (
        {"fixture": "bcl-1/lenient-checker/correct", "status": "ran"},
        {"fixture": "bcl-1/lenient-checker/correct", "status": "error", "flagged": []},
    ):
        document = _results(_perfect)
        document["results"][0] = entry
        with pytest.raises(ValueError, match="flagged is required"):
            read_results(document)


def test_a_weakness_flagged_twice_is_refused() -> None:
    document = _results(_perfect)
    document["results"][1]["flagged"] = ["BGW-101", "BGW-101"]
    with pytest.raises(ValueError, match="twice"):
        read_results(document)


# --------------------------------------------------------------------------- the command


def _write(tmp_path: Path, document: Any) -> Path:
    path = tmp_path / "results.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_the_exit_codes_follow_the_shared_contract(tmp_path: Path) -> None:
    assert main(["conformance", "check", str(_write(tmp_path, _results(_perfect)))]) == CLEAN
    assert main(["conformance", "check", str(_write(tmp_path, _results(lambda _i, _d, w: [w])))]) == FINDINGS
    assert main(["conformance", "check", str(_write(tmp_path, {"not": "results"}))]) == CANNOT_RUN
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert main(["conformance", "check", str(tmp_path / "bad.json")]) == CANNOT_RUN


def test_json_output_is_only_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["conformance", "check", "--json", str(_write(tmp_path, _results(_perfect)))])
    assert json.loads(capsys.readouterr().out)["achieved"] is True


def test_the_rare_command_is_listed_by_help_more_only(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "conformance" not in capsys.readouterr().out
    assert main(["help", "more"]) == CLEAN
    assert "bohrin conformance check FILE" in capsys.readouterr().out
    assert main(["help"]) == CLEAN


def test_the_suites_graders_are_not_part_of_the_installed_library() -> None:
    """They run submissions; the library never does. Only the expected results ship in the package."""
    package = ROOT / "src" / "bohrin" / "conformance"
    assert sorted(p.name for p in package.iterdir() if p.suffix in (".py", ".toml", ".json")) == [
        "__init__.py",
        "bcl-1.toml",
        "conformance-results.v1.json",
    ]


def test_another_level_is_not_published_yet() -> None:
    with pytest.raises(KeyError):
        suite("BCL-2")


def test_results_are_read_into_their_record() -> None:
    results = read_results(_results(_perfect))
    assert isinstance(results, Results) and results.tool == "example" and len(results.results) == 18
