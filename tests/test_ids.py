"""The identifier formats accept exactly the documented shapes."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from bohrin.spec.ids import (
    is_conformance_level,
    is_finding_id,
    is_probe_id,
    is_record_id,
    is_schema_id,
    is_weakness_id,
    weakness_number,
)

CASES: list[tuple[Callable[[str], bool], list[str], list[str]]] = [
    (is_weakness_id, ["BGW-101", "BGW-1", "BGW-10000"], ["BGW-0", "BGW-0101", "bgw-101", "BGW-", "CWE-79", "BGW-101 "]),
    (
        is_record_id,
        ["BVR-2026-00042", "BVR-2027-1234567"],
        ["BVR-2026-0042", "BVR-26-00042", "BVR-2026-", "bvr-2026-00042"],
    ),
    (
        is_probe_id,
        ["bohrin/pytest-report-patch@1", "acme/reward-write@12", "a/b@1"],
        ["bohrin/pytest-report-patch", "bohrin/Pytest@1", "bohrin/x@0", "bohrin/-x@1", "pytest-report-patch@1"],
    ),
    (
        is_finding_id,
        ["BF-7K3Q9D2M1X", "BF-0000000000"],
        [
            "BF-7K3Q9D2M1",
            "BF-7K3Q9D2M1XX",
            "BF-7K3Q9D2M1I",
            "BF-7K3Q9D2M1L",
            "BF-7K3Q9D2M1O",
            "BF-7K3Q9D2M1U",
            "bf-7k3q9d2m1x",
        ],
    ),
    (
        is_schema_id,
        ["https://bohrin.com/schema/finding/v1", "https://bohrin.com/schema/registry-record/v2"],
        [
            "http://bohrin.com/schema/finding/v1",
            "https://bohrin.com/schema/finding/v0",
            "https://bohrin.com/schema/finding",
        ],
    ),
    (is_conformance_level, ["BCL-1", "BCL-4"], ["BCL-0", "BCL-5", "BCL-12", "bcl-1"]),
]


@pytest.mark.parametrize(("check", "good", "bad"), CASES, ids=[c[0].__name__ for c in CASES])
def test_each_format_accepts_its_examples_and_nothing_near_them(
    check: Callable[[str], bool], good: list[str], bad: list[str]
) -> None:
    assert [g for g in good if not check(g)] == []
    assert [b for b in bad if check(b)] == []


def test_weakness_number() -> None:
    assert weakness_number("BGW-108") == 108
    with pytest.raises(ValueError):
        weakness_number("CWE-79")
