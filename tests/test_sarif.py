"""SARIF output and the GitHub Action: valid, stable, and safe to run on pull requests.

The SARIF is validated against the official OASIS SARIF 2.1.0 schema (bundled in ``tests/data``)
and against GitHub's own limits. Fingerprints must keep a fact's identity when its counts change.
The rule table, the rules the code emits and the table in docs/SPEC.md must be one set. The Action
must be pinned, must never paste an input into a shell script, and must use every input it offers.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft4Validator

from bohrin.history.facts import Fact
from bohrin.history.rules import RULES
from bohrin.history.verify import VerifyReport
from bohrin.report.sarif import to_sarif

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((Path(__file__).parent / "data" / "sarif-schema-2.1.0.json").read_text(encoding="utf-8"))
ACTION = ROOT / "action.yml"


def _report(*facts: Fact) -> VerifyReport:
    return VerifyReport(
        since="HEAD~1",
        base="a" * 40,
        changed=tuple(sorted({f.path for f in facts})),
        commits=1,
        facts=facts,
        claims=(),
        not_checked=("files other than Python",),
    )


_FACTS = (
    Fact("check-weakened", "BGW-109", "tests/test_a.py", "test_x was weakened", line=12, subject="test_x"),
    Fact("tests-removed", "BGW-109", "tests/test_gone.py", "tests/test_gone.py deleted"),
    Fact("exit-added", "BGW-102", "src/cli.py", "1 call to exit added", "observation", line=40),
    Fact("selection-changed", "BGW-109", "pytest.ini", "addopts changed", line=2, subject="addopts"),
    Fact("selection-changed", "BGW-109", "pytest.ini", "testpaths changed", line=3, subject="testpaths"),
)


# --------------------------------------------------------------------------- SARIF


@pytest.mark.parametrize("facts", [(), _FACTS], ids=["nothing found", "facts and observations"])
def test_every_log_is_valid_sarif_2_1_0(facts: tuple[Fact, ...]) -> None:
    assert list(Draft4Validator(SCHEMA).iter_errors(to_sarif(_report(*facts)))) == []


def test_github_limits_and_required_fields_hold() -> None:
    run = to_sarif(_report(*_FACTS))["runs"][0]
    for rule in run["tool"]["driver"]["rules"]:
        assert len(rule["name"]) <= 255
        assert 0 < len(rule["shortDescription"]["text"]) <= 1024
        assert 0 < len(rule["fullDescription"]["text"]) <= 1024
        assert rule["help"]["text"] and len(rule["properties"]["tags"]) <= 20
    for result in run["results"]:
        region = result["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] >= 1, "GitHub does not display a result without a start line"
        assert run["tool"]["driver"]["rules"][result["ruleIndex"]]["id"] == result["ruleId"]
    assert run["automationDetails"]["id"].startswith("bohrin-verify/")


def test_facts_warn_and_observations_note() -> None:
    levels = {r["ruleId"]: r["level"] for r in to_sarif(_report(*_FACTS))["runs"][0]["results"]}
    assert levels["check-weakened"] == "warning" and levels["exit-added"] == "note"


def test_a_fact_keeps_its_identity_when_its_counts_change() -> None:
    """A new count must not open a new alert; that is what fingerprints are for."""
    before = Fact("checks-removed", "BGW-109", "tests/test_a.py", "2 assertions removed", line=5)
    after = Fact("checks-removed", "BGW-109", "tests/test_a.py", "3 assertions removed", line=9)
    fingerprint = [to_sarif(_report(f))["runs"][0]["results"][0]["partialFingerprints"] for f in (before, after)]
    assert fingerprint[0] == fingerprint[1]


def test_fingerprints_are_distinct_within_a_run() -> None:
    results = to_sarif(_report(*_FACTS))["runs"][0]["results"]
    prints = [json.dumps(r["partialFingerprints"], sort_keys=True) for r in results]
    assert len(prints) == len(set(prints))


# --------------------------------------------------------------------------- one set of rules


def _emitted_rules() -> set[str]:
    """Every rule name the fact code can emit, read from its source."""
    found = set()
    for source in ("facts.py",):
        tree = ast.parse((ROOT / "src" / "bohrin" / "history" / source).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Fact" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    found.add(first.value)
    return found


def test_the_rule_table_the_code_and_the_specification_agree() -> None:
    spec = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    section = spec[spec.index("## `bohrin verify`") :]
    section = section[: section.index("\n## ", 5)]
    in_spec = set(re.findall(r"^\| `([a-z-]+)` \|", section, re.MULTILINE))

    assert _emitted_rules() == set(RULES), "every emitted rule is described, and nothing else"
    assert in_spec == set(RULES), "docs/SPEC.md lists exactly the rules that exist"


def test_every_rule_names_its_weakness_class_and_kind() -> None:
    for rule_id, rule in RULES.items():
        assert re.fullmatch(r"BGW-[1-9][0-9]*", rule.weakness), rule_id
        assert rule.kind in ("fact", "observation"), rule_id


# --------------------------------------------------------------------------- the Action


def _action() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    return loaded


def test_the_action_never_pastes_an_expression_into_a_shell_script() -> None:
    """GitHub's hardening guide: untrusted values reach scripts through the environment, not ${{ }}."""
    for step in _action()["runs"]["steps"]:
        if "run" in step:
            assert "${{" not in step["run"], step.get("name")


def test_the_action_pins_every_action_it_uses() -> None:
    for step in _action()["runs"]["steps"]:
        if "uses" in step:
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", step["uses"]), step["uses"]


def test_the_action_uses_every_input_it_offers() -> None:
    text = ACTION.read_text(encoding="utf-8")
    for name in _action()["inputs"]:
        assert f"inputs.{name}" in text, f"input {name} is declared but never used"
