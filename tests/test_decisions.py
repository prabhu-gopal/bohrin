"""The decisions file: read strictly, written so it reads back exactly, and never silently permanent.

The file is committed and shared, and a tool writes it from text a person typed, so three things
are held here. Every single-field breakage of a decision is refused, apart from the few that leave
a valid decision. Whatever reason is typed (quotes, newlines, control characters, text that looks
like TOML) is written so it reads back unchanged and cannot add a decision of its own. And an
expiry that cannot be read is an error, never "no expiry".
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft4Validator

from _parity import breakages
from bohrin.decisions import Decision, active, format_decisions, read_decisions, read_decisions_data

ROOT = Path(__file__).resolve().parents[1]
FINDING = "BF-7K3Q9D2M1X"


def _valid() -> dict[str, Any]:
    return {
        "version": 1,
        "decision": [
            {
                "finding": FINDING,
                "action": "ignore",
                "reason": "the task's deliverable is the file's existence",
                "decided": date(2026, 10, 1),
                "expires": date(2027, 1, 1),
            }
        ],
    }


def _accepts(data: dict[str, Any]) -> bool:
    try:
        read_decisions_data(data)
    except (ValueError, TypeError):
        return False
    return True


#: Breakages that still leave a valid file: an optional field removed, or a reason still said.
_STILL_VALID = {"decision removed", "decision = []", "decision.0.expires removed", "decision.0.reason = 'x'"}


def test_every_single_point_breakage_is_refused_unless_it_leaves_a_valid_decision() -> None:
    assert _accepts(_valid())
    wrongly_accepted = [d for d, record in breakages(_valid()) if _accepts(record) and d not in _STILL_VALID]
    wrongly_refused = [d for d, record in breakages(_valid()) if not _accepts(record) and d in _STILL_VALID]
    assert (wrongly_accepted, wrongly_refused) == ([], [])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("decided", "2026-10-01", "written without quotes"),
        ("decided", datetime(2026, 10, 1, 9), "expected a date"),
        ("expires", date(2026, 10, 1), "after the decision date"),
        ("expires", "2027-01-01T00:00:00Z", "expected a date"),
        ("action", "silence", "one of"),
        ("reason", "   ", "say why"),
        ("finding", "BF-0000", "not in the required form"),
        ("by", "someone", "not defined"),
    ],
)
def test_each_rule_is_enforced(field: str, value: Any, message: str) -> None:
    data = _valid()
    data["decision"][0][field] = value
    with pytest.raises(ValueError, match=message):
        read_decisions_data(data)


def test_an_expiry_that_cannot_be_read_is_an_error_never_a_permanent_ignore() -> None:
    text = format_decisions(read_decisions_data(_valid())).replace("expires = 2027-01-01", 'expires = "next year"')
    with pytest.raises(ValueError, match="expires"):
        read_decisions(text)


def test_two_decisions_about_one_finding_are_refused() -> None:
    data = _valid()
    data["decision"].append(dict(data["decision"][0]))
    with pytest.raises(ValueError, match="two decisions"):
        read_decisions_data(data)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("version = 2\n", "version 1"),
        ("version = [\n", "not TOML"),
        ("version = 1\ndecision = 3\n", r"\[\[decision\]\]"),
    ],
)
def test_a_file_this_release_cannot_read_is_refused(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        read_decisions(text)


def test_a_file_with_no_decisions_is_valid() -> None:
    assert read_decisions("version = 1\n") == ()


# --------------------------------------------------------------------------- writing


_REASONS = [
    "plain",
    'quotes " and \\ backslashes',
    "a newline\nand a tab\t",
    "control \x00 \x1b[31m characters",
    "unicode: é, 数, 😀",
    'looks like TOML"\n[[decision]]\nfinding = "BF-AAAAAAAAAA"',
    "  line separator",
]


@pytest.mark.parametrize("reason", _REASONS)
def test_any_reason_reads_back_exactly_and_adds_no_decision(reason: str) -> None:
    decision = Decision(FINDING, "dispute", reason, date(2026, 10, 1))
    assert read_decisions(format_decisions([decision])) == (decision,)


def test_the_file_is_sorted_so_a_change_is_a_small_diff() -> None:
    a = Decision("BF-AAAAAAAAAA", "ignore", "r", date(2026, 10, 1))
    b = Decision("BF-BBBBBBBBBB", "ignore", "r", date(2026, 10, 1))
    assert format_decisions([b, a]) == format_decisions([a, b])
    assert format_decisions([b, a]).index("BF-AAAAAAAAAA") < format_decisions([b, a]).index("BF-BBBBBBBBBB")


# --------------------------------------------------------------------------- meaning


def test_a_decision_holds_until_the_day_it_expires() -> None:
    (decision,) = read_decisions_data(_valid())
    assert FINDING in active([decision], date(2026, 12, 31))
    assert FINDING not in active([decision], date(2027, 1, 1)), "on its expiry date the finding shows again"
    assert Decision(FINDING, "ignore", "r", date(2026, 10, 1)).active(date(2099, 1, 1)), "no expiry holds"


def test_each_decision_is_a_valid_sarif_suppression() -> None:
    schema = json.loads((ROOT / "tests" / "data" / "sarif-schema-2.1.0.json").read_text(encoding="utf-8"))
    suppression = {"$ref": "#/definitions/suppression", "definitions": schema["definitions"]}
    validator = Draft4Validator(suppression)
    for action, status in (("ignore", "accepted"), ("dispute", "underReview")):
        record = Decision(FINDING, action, "why", date(2026, 10, 1)).to_sarif_suppression()
        assert record["status"] == status and record["kind"] == "external" and record["justification"] == "why"
        assert list(validator.iter_errors(record)) == []
