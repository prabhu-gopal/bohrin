"""``bohrin power``: the statistics are right, the audit reports facts, the formats are held to their schemas.

The statistics are checked against independent computations (the standard library's
``statistics`` module, a hand-derived case for clustering). Every audit rule is tested in both
directions, a file that has the defect and one that does not. The input reader is held to its
published schema on every single-field breakage, the JSON report is validated against its schema,
and the command's exit codes follow the shared contract.
"""

from __future__ import annotations

import io
import json
import math
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from _parity import disagreements
from bohrin.cli import CANNOT_RUN, CLEAN, FINDINGS, USAGE, main
from bohrin.scoring.interval import Z_95, wilson_interval
from bohrin.stats.estimates import Z_POWER_80, detectable_difference, standard_error
from bohrin.stats.power import analyse, power_report_schema, render
from bohrin.stats.results import Row, read_results, read_row, results_row_schema


def _rows(*entries: dict[str, Any]) -> list[Row]:
    return read_results(json.dumps(entry) for entry in entries)


def _binary(model: str, passed: list[int], **extra: Any) -> list[dict[str, Any]]:
    return [{"task_id": f"t{i}", "model": model, "score": float(p), **extra} for i, p in enumerate(passed)]


def _weaknesses(rows: list[Row], **kwargs: Any) -> list[str]:
    return [f.weakness for f in analyse(rows, **kwargs).findings]


# --------------------------------------------------------------------------- the statistics


def test_the_standard_error_is_the_textbook_one() -> None:
    values = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.5, 1.0, 1.0]
    assert standard_error(values) == pytest.approx(statistics.stdev(values) / math.sqrt(len(values)))


def test_one_task_per_cluster_is_the_same_as_no_clusters() -> None:
    values = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
    assert standard_error(values, [str(i) for i in range(6)]) == pytest.approx(standard_error(values))


def test_clustering_undoes_the_false_confidence_of_duplicated_tasks() -> None:
    """Every task copied twice looks like twice the evidence; the clustered error knows it is not."""
    values = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0]
    doubled = [v for v in values for _ in range(2)]
    labels = [str(i) for i in range(len(values)) for _ in range(2)]

    naive, clustered, original = standard_error(doubled), standard_error(doubled, labels), standard_error(values)
    assert naive < 0.75 * original, "without clusters the copies make the score look far more certain"
    assert clustered == pytest.approx(original, rel=0.06), "with clusters it is about the honest figure"


def test_the_detectable_difference_is_millers_equation_10() -> None:
    assert detectable_difference(0.05) == pytest.approx((Z_95 + Z_POWER_80) * 0.05)
    assert pytest.approx(2.8016, abs=1e-4) == Z_95 + Z_POWER_80


def test_one_task_has_no_standard_error() -> None:
    assert math.isnan(standard_error([1.0]))


# --------------------------------------------------------------------------- the report


def test_pass_fail_scores_get_the_wilson_interval() -> None:
    passed = [1, 1, 0, 1, 1, 1, 0, 1, 1, 1]
    (model,) = analyse(_rows(*_binary("a", passed))).models

    assert model.method == "Wilson score interval"
    assert model.interval == wilson_interval(8, 10)


def test_graded_scores_get_a_normal_interval_and_a_small_sample_note() -> None:
    rows = _rows(*[{"task_id": f"t{i}", "model": "a", "score": i % 3 / 2} for i in range(30)])
    report = analyse(rows)
    assert report.models[0].method == "normal approximation"
    assert any("fewer than a few hundred" in note for note in report.notes)


def test_scores_are_scaled_by_full_marks_and_samples_are_averaged_per_task() -> None:
    rows = _rows(
        {"task_id": "t0", "model": "a", "score": 10, "max_score": 10, "sample": 0},
        {"task_id": "t0", "model": "a", "score": 0, "max_score": 10, "sample": 1},
        {"task_id": "t1", "model": "a", "score": 10, "max_score": 10, "sample": 0},
        {"task_id": "t1", "model": "a", "score": 10, "max_score": 10, "sample": 1},
    )
    (model,) = analyse(rows).models
    assert (model.tasks, model.samples) == (2, 4)
    assert model.score == pytest.approx(0.75)


def test_errors_count_as_failures_and_the_dropped_figure_is_shown_beside_it() -> None:
    rows = _rows(*_binary("a", [1, 1, 1, 0]), {"task_id": "t4", "model": "a", "score": None})
    report = analyse(rows)
    (model,) = report.models

    assert model.score == pytest.approx(3 / 5)
    assert model.score_errors_dropped == pytest.approx(3 / 4)
    (finding,) = report.findings
    assert finding.weakness == "BGW-128" and "60.0" in finding.message and "75.0" in finding.message


@pytest.mark.parametrize(
    ("rows", "weakness"),
    [
        ([{"task_id": "t0", "model": "a", "score": 1.5}, {"task_id": "t1", "model": "a", "score": 1}], "BGW-128"),
        ([{"task_id": "t0", "model": "a", "score": -1}, {"task_id": "t1", "model": "a", "score": 1}], "BGW-128"),
        ([{"task_id": "t0", "model": "a", "score": 0.4}, {"task_id": "t1", "model": "a", "score": 1}], "BGW-122"),
        (
            [
                {"task_id": "t0", "model": "a", "score": 1, "sample": 0},
                {"task_id": "t0", "model": "a", "score": 0, "sample": 0},
                {"task_id": "t1", "model": "a", "score": 1, "sample": 0},
            ],
            "BGW-128",
        ),
    ],
    ids=["above full marks", "below zero", "partial credit", "same sample twice"],
)
def test_each_aggregation_defect_is_reported(rows: list[dict[str, Any]], weakness: str) -> None:
    assert weakness in _weaknesses(_rows(*rows))


def test_a_clean_file_reports_nothing() -> None:
    """The counterweight: none of the audit rules fires on a well-formed pass/fail file."""
    assert _weaknesses(_rows(*_binary("a", [1, 0, 1, 1]), *_binary("b", [1, 1, 0, 1]))) == []


def test_a_task_missing_for_one_model_is_reported_and_left_out_of_the_comparison() -> None:
    rows = _rows(*_binary("a", [1, 0, 1, 1]), *_binary("b", [1, 1, 0]))
    report = analyse(rows)

    assert [f.model for f in report.findings if f.weakness == "BGW-128"] == ["b"]
    assert report.comparisons[0].tasks == 3


def test_identical_models_are_not_distinguishable() -> None:
    passed = [1, 0, 1, 1, 0, 1, 1, 0]
    (comparison,) = analyse(_rows(*_binary("a", passed), *_binary("b", passed))).comparisons
    assert comparison.difference == 0 and not comparison.distinguishable


def test_a_large_real_difference_is_distinguishable() -> None:
    (comparison,) = analyse(_rows(*_binary("a", [1] * 40), *_binary("b", [1, 0] * 20))).comparisons
    assert comparison.distinguishable and comparison.difference == pytest.approx(0.5)


def test_size_is_judged_only_against_a_difference_the_user_gives() -> None:
    rows = _rows(*_binary("a", [1, 0] * 10))
    assert "BGW-133" not in _weaknesses(rows)
    assert "BGW-133" in _weaknesses(rows, min_difference=0.02)
    assert "BGW-133" not in _weaknesses(rows, min_difference=0.9)


def test_with_two_models_size_is_judged_on_their_paired_comparison() -> None:
    rows = _rows(*_binary("a", [1, 0] * 10), *_binary("b", [0, 1] * 10))
    findings = [f for f in analyse(rows, min_difference=0.02).findings if f.weakness == "BGW-133"]
    assert len(findings) == 1 and findings[0].model is None and "comparing a with b" in findings[0].message


# --------------------------------------------------------------------------- the formats


def test_the_row_reader_and_its_schema_agree_on_every_single_point_breakage() -> None:
    valid = {"task_id": "t0", "model": "a", "score": 0.5, "max_score": 1, "cluster": "repo-1", "sample": 0}

    def accepts(record: dict[str, Any]) -> bool:
        try:
            read_row(record)
        except (ValueError, TypeError):
            return False
        return True

    assert disagreements(valid, results_row_schema(), accepts) == []


def test_a_string_score_is_refused_not_coerced() -> None:
    with pytest.raises(ValueError, match="score"):
        read_row({"task_id": "t0", "model": "a", "score": "1"}, 3)


def test_a_malformed_line_is_refused_with_its_number() -> None:
    with pytest.raises(ValueError, match="line 2"):
        read_results(['{"task_id": "t0", "model": "a", "score": 1}', "not json"])


@pytest.mark.parametrize(
    "rows",
    [
        _binary("a", [1, 0, 1, 1]),
        [*_binary("a", [1, 0, 1, 1], cluster="c"), *_binary("b", [0, 0, 1, 1], cluster="c")],
        [{"task_id": "t0", "model": "a", "score": None}, {"task_id": "t1", "model": "a", "score": 0.5}],
        [{"task_id": "t0", "model": "a", "score": 1}],
    ],
    ids=["one model", "two clustered models", "errors and partial credit", "a single task"],
)
def test_every_json_report_conforms_to_its_schema(rows: list[dict[str, Any]]) -> None:
    report = analyse(_rows(*rows), source="results.jsonl", min_difference=0.02).to_json()
    assert list(Draft202012Validator(power_report_schema()).iter_errors(report)) == []


# --------------------------------------------------------------------------- the command


def _file(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / "results.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_the_exit_codes_follow_the_shared_contract(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clean = _file(tmp_path, [*_binary("a", [1, 0, 1, 1]), *_binary("b", [1, 1, 0, 1])])
    assert main(["power", str(clean)]) == CLEAN
    assert main(["power", str(clean), "--min-difference", "0.02"]) == FINDINGS
    assert main(["power", str(tmp_path / "missing.jsonl")]) == CANNOT_RUN
    (tmp_path / "bad.jsonl").write_text("not json\n", encoding="utf-8")
    assert main(["power", str(tmp_path / "bad.jsonl")]) == CANNOT_RUN
    assert "line 1" in capsys.readouterr().err, "a refusal names the line at fault"
    with pytest.raises(SystemExit) as usage:
        main(["power", str(clean), "--min-difference", "5"])
    assert usage.value.code == USAGE


def test_json_output_is_only_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _file(tmp_path, _binary("a", [1, 0, 1, 1]))
    main(["power", str(path), "--json"])
    printed = capsys.readouterr().out
    assert json.loads(printed)["$schema"] == "https://bohrin.com/schema/power-report/v1"


def test_the_module_runs_as_the_command(tmp_path: Path) -> None:
    path = _file(tmp_path, _binary("a", [1, 0, 1, 1]))
    done = subprocess.run(
        [sys.executable, "-m", "bohrin", "power", str(path)], capture_output=True, text=True, check=False
    )
    assert done.returncode == CLEAN
    assert done.stdout.startswith("bohrin power · results.jsonl")


def test_read_results_takes_any_iterable_of_lines() -> None:
    assert len(read_results(io.StringIO('{"task_id": "t0", "model": "a", "score": 1}\n\n'))) == 1


# --------------------------------------------------------------------------- honest wording and error paths


def test_a_detectable_difference_beyond_the_whole_scale_is_said_plainly() -> None:
    """With two tasks the formula gives ~198 points; printing that would mislead."""
    text = render(analyse(_rows(*_binary("a", [1, 0]))))
    assert "too small to detect any difference" in text
    assert "198" not in text


def test_models_that_share_no_tasks_are_said_not_to_be_compared() -> None:
    rows = _rows(*_binary("a", [1, 0]), *[{"task_id": f"u{i}", "model": "b", "score": 1.0} for i in range(2)])
    report = analyse(rows)
    assert report.comparisons == ()
    assert "a and b share no tasks, so they were not compared." in report.notes
    assert "not compared" in render(report)


def test_models_sharing_one_task_are_said_to_be_too_few_to_compare() -> None:
    rows = _rows(*_binary("a", [1, 0]), {"task_id": "t0", "model": "b", "score": 0.0})
    report = analyse(rows)
    assert "a and b share only 1 task, too few to compare." in report.notes
    assert " − " not in render(report), "a comparison with no interval is not printed as one"


def test_a_single_task_has_no_interval_and_says_so() -> None:
    text = render(analyse(_rows({"task_id": "t0", "model": "a", "score": 0.5})))
    assert "too small to estimate" in text


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (["[1, 2]"], "expected a JSON object"),
        (['{"task_id": "t0", "model": "a", "score": 1, "max_score": 0}'], "max_score"),
        (["", "   "], "no results"),
        (['{"task_id": "t0", "model": "a"}'], "missing"),
    ],
)
def test_an_unusable_file_is_refused_with_a_reason(lines: list[str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        read_results(lines)


def test_a_file_that_is_not_utf8_cannot_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "results.jsonl"
    path.write_bytes(b"\xff\xfe\x00not utf-8")
    assert main(["power", str(path)]) == CANNOT_RUN
    assert "not UTF-8" in capsys.readouterr().err


def test_no_arguments_prints_the_commands(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == CLEAN
    assert "power" in capsys.readouterr().out
