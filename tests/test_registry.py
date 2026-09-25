"""The registry record: its schema and reader agree, and the notification policy is enforced.

A record is the public, citable form of a defect, so it is held to three things. The schema and
the reader give the same verdict on every single-field breakage. The fields the record shares with
the finding record have one definition. And no record passes that was published before the
maintainer had 45 days, unless the defect is fixed and the maintainer agreed.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from _parity import disagreements
from bohrin.registry import NOTICE_DAYS, REGISTRY_RECORD_SCHEMA, read_record, registry_record_schema

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "docs" / "examples" / "BVR-0000-00000.json"


def _example() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    return loaded


def _complete() -> dict[str, Any]:
    """A record using every field, for the parity test."""
    record = _example()
    record.update(
        aliases=["GHSA-xxxx-xxxx-xxxx"],
        related=["BVR-0000-00001"],
        references=[{"type": "FIX", "url": "https://example.org/fix"}],
        credits=[{"name": "Example Finder", "contact": ["https://example.org"], "type": "FINDER"}],
    )
    record["affected"][0]["ranges"] = [
        {"type": "GIT", "repo": "https://example.org/repo", "events": [{"introduced": "0"}, {"fixed": "abc123"}]}
    ]
    record["affected"][0]["versions"] = ["1.0.0"]
    record["disclosure"]["maintainer_agreed_early"] = False
    return record


def _accepts(record: dict[str, Any]) -> bool:
    try:
        read_record(record)
    except (ValueError, TypeError):
        return False
    return True


# --------------------------------------------------------------------------- the published format


def test_the_schema_is_valid_and_published_at_its_id() -> None:
    Draft202012Validator.check_schema(registry_record_schema())
    assert registry_record_schema()["$id"] == REGISTRY_RECORD_SCHEMA


@pytest.mark.parametrize("record", [_example(), _complete()], ids=["the example", "every field"])
def test_a_valid_record_passes_both_the_schema_and_the_reader(record: dict[str, Any]) -> None:
    assert list(Draft202012Validator(registry_record_schema()).iter_errors(record)) == []
    assert read_record(record).document == record


def test_the_reader_and_its_schema_agree_on_every_single_point_breakage() -> None:
    assert disagreements(_complete(), registry_record_schema(), _accepts) == []


def test_the_withdrawn_variant_also_agrees() -> None:
    record = _complete()
    record.update(status="withdrawn", withdrawn="2027-01-02T00:00:00Z")
    assert _accepts(record)
    assert disagreements(record, registry_record_schema(), _accepts) == []


def test_fields_shared_with_the_finding_record_have_one_definition() -> None:
    finding = json.loads((ROOT / "src" / "bohrin" / "evidence" / "finding.v1.json").read_text(encoding="utf-8"))
    record = registry_record_schema()
    assert record["$defs"]["submission"] == finding["properties"]["submission"]
    assert record["$defs"]["digest"] == finding["$defs"]["digest"]
    assert record["properties"]["reproduce"] == finding["properties"]["reproduce"] | {
        "description": record["properties"]["reproduce"]["description"]
    }
    assert record["properties"]["score_received"]["properties"] == finding["properties"]["verdict"]["properties"]


# --------------------------------------------------------------------------- the notification policy


def _published_after(days: float, status: str = "confirmed", agreed: bool | None = None) -> dict[str, Any]:
    record = _example()
    record["disclosure"] = {"maintainer_notified": "2026-10-01T09:00:00Z"}
    if agreed is not None:
        record["disclosure"]["maintainer_agreed_early"] = agreed
    from datetime import datetime, timedelta

    published = datetime(2026, 10, 1, 9) + timedelta(days=days)
    record["published"] = record["modified"] = published.strftime("%Y-%m-%dT%H:%M:%SZ")
    record["status"] = status
    return record


def test_a_record_published_45_days_after_notice_passes() -> None:
    assert _accepts(_published_after(NOTICE_DAYS))


@pytest.mark.parametrize("days", [0, 1, 44, NOTICE_DAYS - 1 / 24])
def test_a_record_published_before_45_days_is_refused(days: float) -> None:
    with pytest.raises(ValueError, match="45 days"):
        read_record(_published_after(days))


def test_a_fixed_defect_may_be_published_early_only_with_the_maintainers_agreement() -> None:
    assert _accepts(_published_after(10, status="fixed", agreed=True))
    for status, agreed in (("fixed", False), ("fixed", None), ("confirmed", True), ("disputed", True)):
        assert not _accepts(_published_after(10, status=status, agreed=agreed)), (status, agreed)


def test_a_record_is_never_published_before_the_maintainer_was_told() -> None:
    with pytest.raises(ValueError, match="never published before"):
        read_record(_published_after(-1, status="fixed", agreed=True))


# --------------------------------------------------------------------------- rules no schema can express


def test_a_date_that_does_not_exist_is_refused() -> None:
    record = _published_after(NOTICE_DAYS)
    record["published"] = "2026-02-30T09:00:00Z"
    # The schema's pattern cannot tell February 30th from a real day; the reader can.
    assert list(Draft202012Validator(registry_record_schema()).iter_errors(record)) == []
    with pytest.raises(ValueError, match="not a real date"):
        read_record(record)


def test_a_weakness_the_list_does_not_have_is_refused() -> None:
    record = _example()
    record["weakness"] = ["BGW-999"]
    with pytest.raises(ValueError, match="not classes of the weakness list"):
        read_record(record)


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("affected", 0, "ranges"), [{"type": "GIT", "events": [{"introduced": "0"}]}], "needs the repository"),
        (
            ("affected", 0, "ranges"),
            [{"type": "SEMVER", "events": [{"introduced": "0", "fixed": "1.0.0"}]}],
            "exactly one",
        ),
        (("affected", 0, "ranges"), [{"type": "SEMVER", "events": []}], "at least one event"),
        (("weakness",), ["BGW-101", "BGW-101"], "twice"),
        (("summary",), "x" * 121, "120 characters"),
        (("status",), "withdrawn", "withdrawn"),
    ],
)
def test_each_structural_rule_is_enforced(path: tuple[Any, ...], value: Any, message: str) -> None:
    record = copy.deepcopy(_complete())
    target = record
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = value
    assert list(Draft202012Validator(registry_record_schema()).iter_errors(record)), "the schema refuses it too"
    with pytest.raises(ValueError, match=message):
        read_record(record)


# --------------------------------------------------------------------------- the example


def test_the_example_is_about_our_own_example_grader_and_names_no_one_else() -> None:
    record = read_record(_example())
    (affected,) = record.affected
    assert affected.artifact.repository == "https://github.com/prabhu-gopal/bohrin"
    assert (ROOT / affected.artifact.name).is_file()
    assert record.id.startswith("BVR-0000-"), "year 0000 marks an example; no real record uses it"


def test_the_example_matches_the_finding_and_the_script_it_cites() -> None:
    record = read_record(_example())
    script = ROOT / "docs" / "examples" / record.document["reproduce"]["script"]
    assert record.reproduce is not None
    assert record.reproduce.sha256 == "sha256:" + hashlib.sha256(script.read_bytes()).hexdigest()
    source = script.read_text(encoding="utf-8")
    assert record.document["findings"][0] in source and record.document["probe"] in source
    assert record.submission is not None and record.submission.sha256 in source
