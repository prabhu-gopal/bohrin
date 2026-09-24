"""Reproduction scripts: the contract, the reading of a result, and invariant I7.

The example script in docs/examples is run for real, checked statically and validated against
the published result schema. Every rule is then broken one at a time: a script that declares the
wrong finding, a result whose claimed outcome contradicts its own runs, an exit code that
disagrees, too few runs to show reliability. A reproduction may take a finding's proof away. It
must never add one.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from _parity import disagreements
from bohrin.evidence import Finding, Reproduction, Scored, Submission, finding_id
from bohrin.evidence.reproduction import (
    OUTCOMES,
    RESULT_SCHEMA,
    SCRIPT_SCHEMA,
    apply,
    check_script,
    judge,
    parse_result,
    reproduction_result_schema,
    script_metadata,
)
from bohrin.ir.task import Ground, Shape, Source, Workspace

EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples"
SCRIPT = EXAMPLES / "reproduce_BF-GZW6R2M9CJ.py"
_VALIDATOR = Draft202012Validator(reproduction_result_schema())

pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="no docs/examples in this checkout")

_SUBMISSION = Submission.of(Source("def add(a, b):\n    pass\n"))
_FINDING = Finding(
    id=finding_id("bohrin/empty-implementation@1", "add", "toy_grader.grade", _SUBMISSION),
    weakness="BGW-101",
    probe="bohrin/empty-implementation@1",
    level="proven",
    task_id="add",
    shape=Shape.PROGRAM,
    battery=2,
    submission=_SUBMISSION,
    ground=Ground.STRUCTURAL,
    verdict=Scored(reward=1.0, passed=True),
    baseline_passed=True,
    reproduce=Reproduction(script=SCRIPT.name, sha256="sha256:" + "0" * 64),
)

PASS = Scored(reward=1.0, passed=True)
FAIL = Scored(reward=0.0, passed=False)


def _run(script: Path, cwd: Path = EXAMPLES) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script)], cwd=cwd, capture_output=True, text=True, check=False)


def _report(runs: list[Scored], baseline: list[Scored], outcome: str, **extra: Any) -> str:
    data: dict[str, Any] = {
        "$schema": RESULT_SCHEMA,
        "finding": _FINDING.id,
        "submission": _SUBMISSION.to_json(),
        "runs": [{"reward": r.reward, "passed": r.passed} for r in runs],
        "baseline_runs": [{"reward": r.reward, "passed": r.passed} for r in baseline],
        "outcome": outcome,
        **extra,
    }
    return json.dumps(data)


# --------------------------------------------------------------------------- the example, for real


def test_the_example_script_meets_the_contract() -> None:
    assert _FINDING.id == "BF-GZW6R2M9CJ", "the example's file name and header must name its real ID"
    assert check_script(SCRIPT.read_text(encoding="utf-8"), _FINDING) == []


def test_the_example_reproduces_its_finding_and_the_finding_stays_proven() -> None:
    done = _run(SCRIPT)
    last = done.stdout.strip().splitlines()[-1]

    assert list(_VALIDATOR.iter_errors(json.loads(last))) == []
    result = parse_result(done.stdout, done.returncode)
    assert (result.outcome, len(result.runs), len(result.baseline_runs)) == ("reproduced", 3, 3)
    assert apply(_FINDING, result) == _FINDING


def test_a_tampered_submission_is_caught_by_the_script_itself(tmp_path: Path) -> None:
    """Edit the embedded submission without its digest, and the script refuses to run it."""
    tampered = tmp_path / SCRIPT.name
    tampered.write_text(
        SCRIPT.read_text(encoding="utf-8").replace(
            'SUBMISSION = "def add(a, b):\\n    pass\\n"', 'SUBMISSION = "x = 1"'
        ),
        encoding="utf-8",
    )
    (tmp_path / "toy_grader.py").write_text((EXAMPLES / "toy_grader.py").read_text(encoding="utf-8"), encoding="utf-8")

    done = _run(tampered, cwd=tmp_path)
    result = parse_result(done.stdout, done.returncode)
    assert (result.outcome, done.returncode) == ("error", OUTCOMES["error"][0])
    assert "digest" in result.error
    assert apply(_FINDING, result).level == "excluded"


# --------------------------------------------------------------------------- the static check


def test_the_inline_metadata_is_read_the_way_pep_723_specifies() -> None:
    metadata = script_metadata(SCRIPT.read_text(encoding="utf-8"))
    assert metadata["requires-python"] == ">=3.11"
    assert metadata["tool"]["bohrin"]["schema"] == SCRIPT_SCHEMA


@pytest.mark.parametrize(
    ("problem", "old", "new"),
    [
        ("another finding", 'finding = "BF-GZW6R2M9CJ"', 'finding = "BF-0000000000"'),
        ("another probe", 'probe = "bohrin/empty-implementation@1"', 'probe = "bohrin/other@1"'),
        ("another submission", "sha256:60a654ef", "sha256:70a654ef"),
        ("too few runs", "# runs = 3", "# runs = 1"),
        ("wrong schema", 'schema = "https://bohrin.com/schema/reproduction/v1"', 'schema = "x"'),
        ("imports bohrin", "import hashlib\n", "import hashlib\nimport bohrin\n"),
        ("reaches the network", "import hashlib\n", "import hashlib\nimport urllib.request\n"),
        ("never reports a result", "https://bohrin.com/schema/reproduction-result/v1", "result"),
        ("no inline metadata", "# /// script\n", "# script\n"),
        ("no requires-python", '# requires-python = ">=3.11"\n', ""),
        ("grades in its own process", "import subprocess\n", ""),
    ],
)
def test_a_script_breaking_one_rule_is_reported(problem: str, old: str, new: str) -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert old in text, problem
    assert check_script(text.replace(old, new), _FINDING) != [], problem


def test_two_script_blocks_are_refused() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    block = text[text.index("# /// script") : text.index("# ///\n", text.index("# /// script") + 5) + 6]
    with pytest.raises(ValueError, match="one"):
        script_metadata(block + "x = 1\n" + block)
    # Adjacent blocks read as one under PEP 723's reference expression, with every key twice:
    # still refused, as the PEP's own reference implementation refuses it.
    with pytest.raises(ValueError):
        script_metadata(block + block)


# --------------------------------------------------------------------------- reading a result


@pytest.mark.parametrize(
    ("runs", "baseline", "expected"),
    [
        ([PASS] * 3, [PASS] * 3, "reproduced"),
        ([FAIL] * 3, [PASS] * 3, "not-reproduced"),
        ([PASS, FAIL, PASS], [PASS] * 3, "flaky"),
        ([PASS] * 3, [PASS, FAIL, PASS], "flaky"),
        ([PASS] * 3, [FAIL] * 3, "baseline-failed"),
        ([PASS] * 2, [PASS] * 3, "error"),
        ([PASS] * 3, [PASS] * 2, "error"),
    ],
)
def test_the_outcome_is_what_the_runs_support(runs: list[Scored], baseline: list[Scored], expected: str) -> None:
    assert judge(runs, baseline) == expected


@pytest.mark.parametrize(
    ("problem", "stdout", "exit_code"),
    [
        ("claims reproduced but was never paid", _report([FAIL] * 3, [PASS] * 3, "reproduced"), 0),
        ("claims reproduced on one lucky run", _report([PASS], [PASS], "reproduced"), 0),
        ("exit code disagrees", _report([PASS] * 3, [PASS] * 3, "reproduced"), 1),
        ("hides a flaky grader", _report([PASS, FAIL, PASS], [PASS] * 3, "reproduced"), 0),
        ("not a result", '{"reward": 1.0}', 0),
        ("not JSON", "reward: 1.0", 0),
        ("nothing printed", "", 0),
    ],
)
def test_a_result_that_contradicts_itself_is_refused(problem: str, stdout: str, exit_code: int) -> None:
    with pytest.raises(ValueError):
        parse_result(stdout, exit_code)


def test_only_the_last_line_is_the_result() -> None:
    stdout = "the grader logged something\n" + _report([PASS] * 3, [PASS] * 3, "reproduced") + "\n"
    assert parse_result(stdout, 0).outcome == "reproduced"


# --------------------------------------------------------------------------- invariant I7


@pytest.mark.parametrize(
    ("runs", "baseline", "outcome", "level"),
    [
        ([FAIL] * 3, [PASS] * 3, "not-reproduced", "lead"),
        ([PASS, FAIL, PASS], [PASS] * 3, "flaky", "lead"),
        ([PASS] * 3, [FAIL] * 3, "baseline-failed", "excluded"),
    ],
)
def test_a_finding_that_does_not_reproduce_loses_its_proof(
    runs: list[Scored], baseline: list[Scored], outcome: str, level: str
) -> None:
    result = parse_result(_report(runs, baseline, outcome), OUTCOMES[outcome][0])
    downgraded = apply(_FINDING, result)

    assert downgraded.level == level
    assert outcome in downgraded.reason


_RESULTS = {
    "reproduced": ([PASS] * 3, [PASS] * 3),
    "not-reproduced": ([FAIL] * 3, [PASS] * 3),
    "flaky": ([PASS, FAIL, PASS], [PASS] * 3),
    "baseline-failed": ([PASS] * 3, [FAIL] * 3),
}


@pytest.mark.parametrize("level", ["lead", "excluded", "suspected", "observation"])
@pytest.mark.parametrize("outcome", list(_RESULTS))
def test_a_reproduction_never_changes_a_finding_that_was_not_proven(level: str, outcome: str) -> None:
    """Only a proven finding has proof to lose; nothing else moves, in either direction."""
    finding = Finding(**{**_finding_fields(), "level": level, "reason": "not established"})
    runs, baseline = _RESULTS[outcome]
    result = parse_result(_report(runs, baseline, outcome), OUTCOMES[outcome][0])
    assert apply(finding, result) == finding


def test_a_result_for_another_finding_or_submission_is_refused() -> None:
    other_id = _report([PASS] * 3, [PASS] * 3, "reproduced").replace(_FINDING.id, "BF-0000000000")
    with pytest.raises(ValueError, match="not"):
        apply(_FINDING, parse_result(other_id, 0))
    other_submission = _report([PASS] * 3, [PASS] * 3, "reproduced").replace("sha256:60a6", "sha256:70a6")
    with pytest.raises(ValueError, match="different submission"):
        apply(_FINDING, parse_result(other_submission, 0))


def _finding_fields() -> dict[str, Any]:
    return {name: getattr(_FINDING, name) for name in Finding.__dataclass_fields__}


# --------------------------------------------------------------------------- the published schema


def test_the_result_schema_is_valid_and_published_at_its_id() -> None:
    Draft202012Validator.check_schema(reproduction_result_schema())
    assert reproduction_result_schema()["$id"] == RESULT_SCHEMA


@pytest.mark.parametrize(
    "report",
    [
        _report([PASS] * 2, [PASS] * 3, "reproduced"),
        _report([], [], "error"),
        _report([PASS] * 3, [PASS] * 3, "maybe"),
        _report([PASS] * 3, [PASS] * 3, "reproduced", confidence=0.9),
    ],
)
def test_the_schema_refuses_a_result_the_reader_refuses(report: str) -> None:
    assert list(_VALIDATOR.iter_errors(json.loads(report)))
    with pytest.raises((ValueError, KeyError)):
        parse_result(report, 0)


# --------------------------------------------------------------------------- workspace submissions


def test_a_script_can_declare_a_workspace_that_deletes_files() -> None:
    """TOML has no null, so deletions are listed under ``deleted`` and read back as the record's nulls."""
    submission = Submission.of(Workspace({"tests/test_a.py": None, "src/a.py": "x = 1\n"}, commands=("true",)))
    finding = Finding(**{**_finding_fields(), "submission": submission, "shape": Shape.WORKSPACE})
    digest = submission.to_json()["files"]["src/a.py"]
    header = (
        "# /// script\n"
        '# requires-python = ">=3.11"\n'
        "#\n"
        "# [tool.bohrin]\n"
        f'# schema = "{SCRIPT_SCHEMA}"\n'
        f'# finding = "{finding.id}"\n'
        f'# probe = "{finding.probe}"\n'
        "# runs = 3\n"
        "#\n"
        "# [tool.bohrin.submission]\n"
        '# kind = "workspace"\n'
        '# deleted = ["tests/test_a.py"]\n'
        '# commands = ["true"]\n'
        "# parameters = []\n"
        "#\n"
        "# [tool.bohrin.submission.files]\n"
        f'# "src/a.py" = "{digest}"\n'
        "# ///\n"
        "import subprocess\n"
        f'print("{RESULT_SCHEMA}")\n'
    )
    assert check_script(header, finding) == []
    assert check_script(header.replace('# deleted = ["tests/test_a.py"]\n', "# deleted = []\n"), finding) != []


# --------------------------------------------------------------------------- schema parity, exhaustively


@pytest.mark.parametrize(
    ("outcome", "runs", "baseline"),
    [("reproduced", [PASS] * 3, [PASS] * 3), ("not-reproduced", [FAIL] * 3, [PASS] * 3)],
)
def test_the_reader_and_the_result_schema_agree_on_every_single_point_breakage(
    outcome: str, runs: list[Scored], baseline: list[Scored]
) -> None:
    valid = json.loads(_report(runs, baseline, outcome, python="3.13.5", platform="Linux"))

    def accepts(record: dict[str, Any]) -> bool:
        try:
            parse_result(json.dumps(record), OUTCOMES[outcome][0])
        except ValueError as exc:
            # Comparing the claimed outcome with the runs is a cross-field rule JSON Schema cannot
            # express. It has its own tests above; parity is about each field on its own.
            return "but its runs show" in str(exc)
        except TypeError:
            return False
        return True

    assert disagreements(valid, reproduction_result_schema(), accepts) == []


def test_a_passed_written_as_a_string_is_not_read_as_true() -> None:
    """The dangerous coercion: ``"false"`` read as passed would turn a failure into a reproduction."""
    line = json.loads(_report([PASS] * 3, [PASS] * 3, "reproduced"))
    line["runs"] = [{"reward": 0.0, "passed": "false"}] * 3
    with pytest.raises(ValueError, match="true or false"):
        parse_result(json.dumps(line), 0)


# --------------------------------------------------------------------------- a submission cannot stop the script


def _variant(tmp_path: Path, submission: str) -> Path:
    """The example script with another submission embedded, digest and all."""
    import hashlib

    digest = "sha256:" + hashlib.sha256(submission.encode("utf-8")).hexdigest()
    text = SCRIPT.read_text(encoding="utf-8")
    old = 'SUBMISSION = "def add(a, b):\\n    pass\\n"'
    assert old in text
    old_digest = _SUBMISSION.to_json()["sha256"]
    text = text.replace(old, "SUBMISSION = " + repr(submission)).replace(old_digest, digest)
    (tmp_path / "toy_grader.py").write_text((EXAMPLES / "toy_grader.py").read_text(encoding="utf-8"), encoding="utf-8")
    script = tmp_path / SCRIPT.name
    script.write_text(text, encoding="utf-8")
    return script


@pytest.mark.parametrize(
    "submission",
    [
        "import sys\nsys.exit(0)\n",
        "import os\nos._exit(0)\n",
        "raise SystemExit(0)\n",
        "def add(a, b):\n    import os\n    os._exit(0)\n",
        "raise RuntimeError('crash')\n",
    ],
    ids=["sys.exit", "os._exit", "SystemExit", "os._exit inside add", "crash"],
)
def test_a_submission_that_exits_or_crashes_cannot_stop_the_script_reporting(tmp_path: Path, submission: str) -> None:
    """Before each grading ran in its own process, sys.exit(0) ended the script silently with exit code 0."""
    done = _run(_variant(tmp_path, submission), cwd=tmp_path)
    result = parse_result(done.stdout, done.returncode)

    assert result.outcome == "not-reproduced", "no reward reported is not paid: the script fails closed"
    assert done.returncode == OUTCOMES["not-reproduced"][0]
    assert all(run.passed for run in result.baseline_runs), "the reference still ran normally"


def test_a_script_that_is_not_python_is_reported() -> None:
    text = SCRIPT.read_text(encoding="utf-8") + "\ndef broken(:\n"
    assert any("not valid Python" in problem for problem in check_script(text, _FINDING))
