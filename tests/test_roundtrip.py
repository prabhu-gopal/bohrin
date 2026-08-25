"""Report JSON round-trip with a stable schema version (docs/06 P1 DoD)."""

from __future__ import annotations

import _synth
import bohrin
from bohrin.report.model import Report
from bohrin.version import REPORT_SCHEMA_VERSION


def _report() -> Report:
    path = _synth.register_memory_dataset(_synth.inject_dead_dimension(_synth.clean_dataset()))
    return bohrin.scan(path)


def test_report_round_trips_through_json() -> None:
    report = _report()
    restored = Report.from_json(report.to_json())
    assert restored == report
    assert restored.schema_version == REPORT_SCHEMA_VERSION


def test_round_trip_preserves_findings_and_provenance() -> None:
    report = _report()
    restored = Report.from_json(report.to_json())
    original = report.cluster("stats.dead_dimension")
    round_tripped = restored.cluster("stats.dead_dimension")
    assert original is not None and round_tripped is not None
    assert round_tripped.findings[0].provenance.adapter == "memory"
    assert round_tripped.findings[0] == original.findings[0]


def test_schema_version_is_stamped() -> None:
    assert _report().schema_version == "1.0"
