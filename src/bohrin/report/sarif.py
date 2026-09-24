"""SARIF 2.1.0 output, so facts appear as annotations on a pull request.

SARIF (the OASIS Static Analysis Results Interchange Format) is what GitHub code scanning and many
other review tools read. This follows GitHub's documented subset
(https://docs.github.com/en/code-security/reference/code-scanning/sarif-files/sarif-support-for-code-scanning):

* every rule has an ``id``, a ``name``, short and full descriptions and help;
* every result has a message, a location with ``region.startLine``, and ``partialFingerprints``, so
  the same fact keeps its alert across runs instead of opening a new one;
* the run carries ``automationDetails.id`` with a category, so Bohrin's results never replace another
  tool's.

A fact is a ``warning`` and an observation a ``note``. The fingerprint is built from the rule, the
path and the subject (the test or function), never the message, so a count that changes does not
make a new alert.
"""

from __future__ import annotations

import hashlib
from typing import Any

from bohrin.history.rules import RULES
from bohrin.history.verify import VerifyReport
from bohrin.version import __version__

SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
SPEC_URL = "https://github.com/prabhu-gopal/bohrin/blob/main/docs/SPEC.md#bohrin-verify"
CATEGORY = "bohrin-verify"


def _fingerprint(rule: str, path: str, subject: str) -> str:
    """Identity across runs: the rule, the file and the subject; never the message, whose counts change."""
    key = f"{rule}\0{path}\0{subject}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def to_sarif(report: VerifyReport) -> dict[str, Any]:
    """The report as a SARIF 2.1.0 log with one run."""
    rule_ids = sorted(RULES)
    rules = [
        {
            "id": rule_id,
            "name": RULES[rule_id].name,
            "shortDescription": {"text": RULES[rule_id].summary},
            "fullDescription": {"text": f"{RULES[rule_id].summary} {RULES[rule_id].help}"},
            "help": {
                "text": RULES[rule_id].help,
                "markdown": f"{RULES[rule_id].help}\n\n[How verify works]({SPEC_URL})",
            },
            "helpUri": SPEC_URL,
            "defaultConfiguration": {"level": "warning" if RULES[rule_id].kind == "fact" else "note"},
            "properties": {
                "tags": ["tests", RULES[rule_id].weakness, RULES[rule_id].kind],
                "precision": "very-high" if RULES[rule_id].kind == "fact" else "high",
                "problem.severity": "warning" if RULES[rule_id].kind == "fact" else "recommendation",
            },
        }
        for rule_id in rule_ids
    ]
    results = []
    for fact in report.facts:
        line = fact.line or 1
        results.append(
            {
                "ruleId": fact.rule,
                "ruleIndex": rule_ids.index(fact.rule),
                "level": "warning" if fact.kind == "fact" else "note",
                "message": {"text": f"{fact.message} ({fact.weakness})"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": fact.path},
                            "region": {"startLine": line, "startColumn": 1, "endLine": line, "endColumn": 1},
                        }
                    }
                ],
                "partialFingerprints": {"bohrinFact/v1": _fingerprint(fact.rule, fact.path, fact.subject)},
                "properties": {"weakness": fact.weakness, "kind": fact.kind},
            }
        )
    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "bohrin",
                        "version": __version__,
                        "informationUri": "https://github.com/prabhu-gopal/bohrin",
                        "rules": rules,
                    }
                },
                "automationDetails": {"id": f"{CATEGORY}/"},
                "properties": {"since": report.since, "base": report.base, "notChecked": list(report.not_checked)},
                "results": results,
            }
        ],
    }


__all__ = ["CATEGORY", "SARIF_SCHEMA", "to_sarif"]
