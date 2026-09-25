"""The error-rate method: every rate carries its sample and interval, and nothing is counted twice.

Precision counts a false accusation only when a finding was overturned, leaves an open dispute out
of both sides, and keeps experimental findings out of the headline. Recall follows Magma's three
stages, each implying the one before. Both input formats agree with their schemas on every
single-field breakage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from _parity import disagreements
from bohrin.stats.error_rate import (
    FINDING_OUTCOME_SCHEMA,
    RECALL_ROW_SCHEMA,
    Outcome,
    Planted,
    finding_outcome_schema,
    precision,
    read_lines,
    read_outcome,
    read_planted,
    recall,
    recall_row_schema,
    render,
)

ROOT = Path(__file__).resolve().parents[1]
EMPTY = "bohrin/empty-implementation@1"
CONSTANT = "bohrin/constant-implementation@1"


def _outcome(n: int, outcome: str = "stands", probe: str = EMPTY, **extra: Any) -> Outcome:
    fields: dict[str, Any] = {"battery": 2, "level": "proven", "dismissed": False} | extra
    return Outcome(f"BF-{n:010d}", probe, fields["battery"], fields["level"], outcome, fields["dismissed"])


def test_no_false_accusation_in_forty_reads_as_at_most_88_per_thousand_not_never() -> None:
    (overall, _) = precision([_outcome(n) for n in range(40)])
    assert overall.per_thousand == 0.0
    assert overall.interval_per_thousand is not None and round(overall.interval_per_thousand[1]) == 88
    assert "0 false accusations per 1,000 (95% CI 0–88), 0 of 40" in render([overall])


def test_only_an_overturned_finding_is_a_false_accusation() -> None:
    rows = [
        _outcome(1),
        _outcome(2, "withdrawn-after-dispute"),
        _outcome(3, "contradicted-by-fixture"),
        _outcome(4, "stands", dismissed=True),
    ]
    (overall, _) = precision(rows)
    assert (overall.false, overall.resolved) == (2, 4)
    assert overall.per_thousand == 500.0
    assert overall.dismissal_rate == 0.25, "a dismissal is reported beside the rate, never counted as an error"


def test_an_open_dispute_counts_neither_way_and_is_named() -> None:
    (overall, _) = precision([_outcome(1), _outcome(2, "disputed")])
    assert (overall.false, overall.resolved, overall.disputed, overall.reported) == (0, 1, 1, 2)
    assert "1 under open dispute, counted neither way" in render([overall])


def test_experimental_findings_never_enter_the_headline() -> None:
    rows = [_outcome(1), _outcome(2, "withdrawn-after-dispute", level="proven-experimental")]
    (headline, _) = precision(rows)
    assert headline.false == 0 and headline.reported == 1
    (experimental, _) = precision(rows, level="proven-experimental")
    assert experimental.false == 1


def test_rates_are_per_battery_then_per_probe() -> None:
    rows = [
        _outcome(1),
        _outcome(2, probe=CONSTANT),
        _outcome(3, "contradicted-by-fixture", probe=CONSTANT),
        _outcome(4, battery=3),
    ]
    groups = [(p.battery, p.probe, p.false, p.resolved) for p in precision(rows)]
    assert groups == [(2, None, 1, 3), (2, CONSTANT, 1, 2), (2, EMPTY, 0, 1), (3, None, 0, 1), (3, EMPTY, 0, 1)]


def test_nothing_resolved_is_not_a_rate() -> None:
    (only_disputed, _) = precision([_outcome(1, "disputed")])
    assert only_disputed.per_thousand is None and only_disputed.interval_per_thousand is None
    assert "no resolved finding yet" in render([only_disputed])
    assert precision([]) == ()


# --------------------------------------------------------------------------- recall


def _planted(instance: str, tried: bool, accepted: bool, proven: bool, weakness: str = "BGW-101") -> Planted:
    return Planted(weakness, instance, tried, accepted, proven)


def test_recall_follows_the_three_stages_per_weakness() -> None:
    rows = [
        _planted("a", True, True, True),
        _planted("b", True, True, False),
        _planted("c", True, False, False),
        _planted("d", False, False, False),
        _planted("e", True, True, True, weakness="BGW-108"),
    ]
    first, second = recall(rows)
    assert (first.weakness, first.planted, first.tried, first.accepted, first.proven) == ("BGW-101", 4, 3, 2, 1)
    assert second.weakness == "BGW-108" and second.interval("proven") is not None
    assert "BGW-101: 4 planted · tried 3" in render([], recall(rows))


def test_a_stage_cannot_be_reached_without_the_one_before() -> None:
    for tried, accepted, proven, message in (
        (False, True, False, "accepted without"),
        (True, False, True, "proven without"),
    ):
        row = {"weakness": "BGW-101", "instance": "a", "tried": tried, "accepted": accepted, "proven": proven}
        with pytest.raises(ValueError, match=message):
            read_planted(row)
        assert list(Draft202012Validator(recall_row_schema()).iter_errors(row)), "the schema refuses it too"


def test_an_instance_listed_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="twice"):
        recall([_planted("a", True, True, True), _planted("a", False, False, False)])


def test_the_weaknesses_are_in_id_order_not_text_order() -> None:
    rows = [_planted("a", True, True, True, weakness="BGW-1000"), _planted("b", True, True, True, weakness="BGW-999")]
    assert [r.weakness for r in recall(rows)] == ["BGW-999", "BGW-1000"]


# --------------------------------------------------------------------------- the published formats


def _accepts(reader: Any) -> Any:
    def accepts(record: dict[str, Any]) -> bool:
        try:
            reader(record)
        except (ValueError, TypeError):
            return False
        return True

    return accepts


def test_both_schemas_are_valid_and_published_at_their_ids() -> None:
    for schema, schema_id in (
        (finding_outcome_schema(), FINDING_OUTCOME_SCHEMA),
        (recall_row_schema(), RECALL_ROW_SCHEMA),
    ):
        Draft202012Validator.check_schema(schema)
        assert schema["$id"] == schema_id


def test_the_outcome_reader_and_its_schema_agree_on_every_single_point_breakage() -> None:
    valid = {
        "finding": "BF-0000000001",
        "probe": EMPTY,
        "battery": 2,
        "level": "proven",
        "outcome": "stands",
        "dismissed": False,
    }
    assert disagreements(valid, finding_outcome_schema(), _accepts(read_outcome)) == []


@pytest.mark.parametrize(
    "stages", [(True, True, True), (True, True, False), (True, False, False), (False, False, False)]
)
def test_the_recall_reader_and_its_schema_agree_on_every_single_point_breakage(stages: tuple[bool, bool, bool]) -> None:
    tried, accepted, proven = stages
    valid = {
        "weakness": "BGW-101",
        "instance": "task-1",
        "tried": tried,
        "accepted": accepted,
        "proven": proven,
        "method": "battery",
    }
    assert disagreements(valid, recall_row_schema(), _accepts(read_planted)) == []


def test_json_lines_are_read_with_their_line_numbers() -> None:
    lines = [
        "",
        json.dumps({"weakness": "BGW-101", "instance": "a", "tried": True, "accepted": False, "proven": False}),
    ]
    (row,) = read_lines(lines, read_planted)
    assert row.instance == "a"
    with pytest.raises(ValueError, match="line 2: not JSON"):
        read_lines(["", "{"], read_planted)


def test_the_errata_file_states_its_format_and_links_the_method() -> None:
    errata = (ROOT / "ERRATA.md").read_text(encoding="utf-8")
    assert "### E<number>" in errata and "Entries are added, never removed" in errata
    assert "docs/SPEC.md#error-rates" in errata
