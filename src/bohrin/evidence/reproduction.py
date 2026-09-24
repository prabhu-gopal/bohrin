"""Reproduction scripts: the contract every proven finding's script follows, and how its result is read.

A proven finding ships with a plain Python script that its reader can run without Bohrin. It
applies the exact submission to the reader's own environment, runs their grader and prints what
happened. That script is the evidence a stranger actually checks, so its shape is fixed here:

* **It is a standard standalone script** (PEP 723 inline metadata). ``uv run`` or ``pipx run``
  can run it as it is, and its ``[tool.bohrin]`` table says which finding it reproduces, which
  probe made it, the submission's digests and how many times it runs.
* **It checks itself.** It verifies the embedded submission against the declared digests before
  running anything.
* **It measures reliability, not a single lucky run.** It runs the reference and the submission
  at least :data:`MIN_RUNS` times each. A finding is reproduced only when the reference passes
  every time and the submission is paid full marks every time; mixed verdicts are ``flaky``.
* **It runs the grader exactly as its owner's harness does**, not hardened: hardening would hide
  the very defects a tamper probe proves.
* **It reports one line of JSON** (``https://bohrin.com/schema/reproduction-result/v1``) and a
  distinct exit code for each outcome.

Reading a result never trusts the script's own verdict: :func:`parse_result` recomputes the
outcome from the recorded runs, and :func:`apply` downgrades a finding whose script did not
reproduce it (invariant I7). A reproduction can remove a finding's proof. It can never add one.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any

from bohrin.evidence.finding import PROVEN, Finding, Scored

SCRIPT_SCHEMA = "https://bohrin.com/schema/reproduction/v1"
RESULT_SCHEMA = "https://bohrin.com/schema/reproduction-result/v1"

#: The fewest runs of the reference and of the submission that can show a verdict is reliable.
MIN_RUNS = 3

#: Each outcome, what it means, and the exit code the script returns for it.
OUTCOMES: Mapping[str, tuple[int, str]] = MappingProxyType(
    {
        "reproduced": (0, "the reference passed every run and the submission was paid full marks every run"),
        "not-reproduced": (1, "the reference passed every run and the submission was never paid full marks"),
        "flaky": (2, "the grader's verdict varied across runs"),
        "baseline-failed": (3, "the reference did not pass its own grader, so nothing can be concluded"),
        "error": (4, "the script could not run the grader"),
    }
)

#: PEP 723's reference expression for an inline metadata block.
_BLOCK = re.compile(r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$")

#: Modules through which a script could reach the network. A reproduction must not need one.
_NETWORK = frozenset(
    {"ftplib", "http", "httpx", "requests", "smtplib", "socket", "ssl", "urllib", "urllib3", "webbrowser"}
)


#: The fields a result may carry. Anything else is a claim this version cannot check.
_RESULT_FIELDS = frozenset(
    {"$schema", "finding", "submission", "runs", "baseline_runs", "outcome", "python", "platform", "error"}
)


@cache
def reproduction_result_schema() -> dict[str, Any]:
    """The JSON Schema published at ``https://bohrin.com/schema/reproduction-result/v1``."""
    text = files("bohrin.evidence").joinpath("reproduction-result.v1.json").read_text("utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


def script_metadata(text: str) -> dict[str, Any]:
    """The script's PEP 723 ``script`` block, parsed. Raises ``ValueError`` if it has not exactly one."""
    blocks = [m for m in _BLOCK.finditer(text) if m.group("type") == "script"]
    if len(blocks) != 1:
        raise ValueError(f"expected one '# /// script' block, found {len(blocks)}")
    content = "".join(
        line[2:] if line.startswith("# ") else line[1:] for line in blocks[0].group("content").splitlines(keepends=True)
    )
    return tomllib.loads(content)


def check_script(text: str, finding: Finding) -> list[str]:
    """Everything wrong with a reproduction script for ``finding``, read without running it.

    An empty list means the script declares the right finding and submission, runs often enough,
    reports in the published format, and neither imports Bohrin nor reaches the network. It does
    not mean the script reproduces the finding: only running it can show that.
    """
    problems: list[str] = []
    try:
        metadata = script_metadata(text)
    except (ValueError, tomllib.TOMLDecodeError) as exc:
        return [f"inline metadata: {exc}"]
    if "requires-python" not in metadata:
        problems.append("inline metadata: no requires-python")
    declared = metadata.get("tool", {}).get("bohrin", {})
    if declared.get("schema") != SCRIPT_SCHEMA:
        problems.append(f"[tool.bohrin] schema is not {SCRIPT_SCHEMA}")
    if declared.get("finding") != finding.id:
        problems.append(f"[tool.bohrin] declares finding {declared.get('finding')!r}, not {finding.id!r}")
    if declared.get("probe") != finding.probe:
        problems.append(f"[tool.bohrin] declares probe {declared.get('probe')!r}, not {finding.probe!r}")
    if finding.submission is None or _declared_submission(declared.get("submission")) != finding.submission.to_json():
        problems.append("[tool.bohrin] submission digests do not match the finding")
    runs = declared.get("runs")
    if not isinstance(runs, int) or runs < MIN_RUNS:
        problems.append(f"[tool.bohrin] runs must be an integer of at least {MIN_RUNS}")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [*problems, f"not valid Python: {exc}"]
    imported = _imports(tree)
    if "bohrin" in imported:
        problems.append("imports bohrin: a reproduction must run without it")
    if imported & _NETWORK:
        problems.append(f"imports network modules {sorted(imported & _NETWORK)}: a reproduction must not need one")
    if RESULT_SCHEMA not in text:
        problems.append(f"never reports a {RESULT_SCHEMA} result")
    return problems


def _declared_submission(table: Any) -> Any:
    """A ``[tool.bohrin.submission]`` table in the finding record's form.

    TOML has no null, so a script lists the files a workspace deletes under ``deleted`` rather than
    as null digests. They are folded back into ``files`` here, as the record writes them.
    """
    if not isinstance(table, dict) or table.get("kind") != "workspace":
        return table
    record = {key: value for key, value in table.items() if key != "deleted"}
    files: dict[str, Any] = dict(table.get("files", {}))
    for path in table.get("deleted", []):
        files[path] = None
    record["files"] = dict(sorted(files.items()))
    return record


def _imports(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def judge(submission_runs: Sequence[Scored], baseline_runs: Sequence[Scored], error: str = "") -> str:
    """The outcome the recorded runs support, whatever the script itself claimed."""
    if error:
        return "error"
    if len(submission_runs) < MIN_RUNS or len(baseline_runs) < MIN_RUNS:
        return "error"
    baseline = {run.passed for run in baseline_runs}
    submission = {run.passed for run in submission_runs}
    if baseline == {False}:
        return "baseline-failed"
    if len(baseline) > 1 or len(submission) > 1:
        return "flaky"
    return "reproduced" if submission == {True} else "not-reproduced"


@dataclass(frozen=True, slots=True)
class ReproductionResult:
    """What a reproduction script reported, and the outcome its runs support."""

    finding: str
    #: The submission the script actually ran, as digests, in the finding record's form.
    submission: Mapping[str, Any]
    runs: tuple[Scored, ...]
    baseline_runs: tuple[Scored, ...]
    #: Recomputed from the runs by :func:`judge`; never taken from the script on trust.
    outcome: str
    python: str = ""
    platform: str = ""
    error: str = ""


def parse_result(stdout: str, exit_code: int) -> ReproductionResult:
    """Read a script's last line of output. Raises ``ValueError`` if it is not a valid result.

    The script's declared outcome and its exit code must both agree with the outcome its runs
    support. A script whose report contradicts its own runs is not evidence of anything.
    """
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise ValueError("the script printed nothing")
    try:
        data = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"the last line is not JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("$schema") != RESULT_SCHEMA:
        raise ValueError(f"the last line is not a {RESULT_SCHEMA} result")
    unknown = sorted(set(data) - _RESULT_FIELDS)
    if unknown:
        raise ValueError(f"fields not defined by {RESULT_SCHEMA}: {unknown}")
    try:
        runs = tuple(Scored(reward=float(r["reward"]), passed=bool(r["passed"])) for r in data["runs"])
        baseline = tuple(Scored(reward=float(r["reward"]), passed=bool(r["passed"])) for r in data["baseline_runs"])
        result = ReproductionResult(
            finding=data["finding"],
            submission=data["submission"],
            runs=runs,
            baseline_runs=baseline,
            outcome=judge(runs, baseline, data.get("error", "")),
            python=data.get("python", ""),
            platform=data.get("platform", ""),
            error=data.get("error", ""),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"the result is missing or mistypes {exc}") from exc
    if result.outcome == "error" and not result.error:
        raise ValueError("an error outcome must say what went wrong")
    if data.get("outcome") != result.outcome:
        raise ValueError(f"the script reported {data.get('outcome')!r}, but its runs show {result.outcome!r}")
    if exit_code != OUTCOMES[result.outcome][0]:
        raise ValueError(f"exit code {exit_code} does not match the outcome {result.outcome!r}")
    return result


def apply(finding: Finding, result: ReproductionResult) -> Finding:
    """The finding as its reproduction leaves it (invariant I7). It can lose its proof, never gain one.

    Raises ``ValueError`` if the result is about another finding or another submission.
    """
    if result.finding != finding.id:
        raise ValueError(f"the result is for {result.finding}, not {finding.id}")
    if finding.submission is None or dict(result.submission) != finding.submission.to_json():
        raise ValueError("the result ran a different submission from the finding's")
    if finding.level not in PROVEN or result.outcome == "reproduced":
        return finding
    reason = f"reproduction {result.outcome}: {OUTCOMES[result.outcome][1]}"
    if result.error:
        reason += f" ({result.error})"
    level = "lead" if result.outcome in ("not-reproduced", "flaky") else "excluded"
    return replace(finding, level=level, reason=reason)


__all__ = [
    "MIN_RUNS",
    "OUTCOMES",
    "RESULT_SCHEMA",
    "SCRIPT_SCHEMA",
    "ReproductionResult",
    "apply",
    "check_script",
    "judge",
    "parse_result",
    "reproduction_result_schema",
    "script_metadata",
]
