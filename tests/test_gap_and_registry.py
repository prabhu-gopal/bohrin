"""The Verification Gap, plugin discovery, and the report contract."""

from __future__ import annotations

import json

import pytest

import _fixtures
from bohrin.probes.base import Probe, ProbeResult, ProbeStatus
from bohrin.probes.determinism import DeterminismProbe
from bohrin.probes.weak_oracle import WeakOracleProbe
from bohrin.report.model import Report
from bohrin.scoring.gap import verification_gap
from bohrin.version import REPORT_SCHEMA_VERSION

PROBES: list[Probe] = [WeakOracleProbe(), DeterminismProbe()]


def _ok(pid: str, score: float) -> ProbeResult:
    return ProbeResult(probe_id=pid, status=ProbeStatus.OK, sub_score=score, tasks_probed=10)


def _skipped(pid: str, status: ProbeStatus) -> ProbeResult:
    return ProbeResult(probe_id=pid, status=status, reason="fixture")


# ------------------------------------------------------------------- the gap arithmetic


def test_gap_is_the_weighted_mean_scaled_to_100() -> None:
    gap = verification_gap([_ok("weak_oracle", 0.5), _ok("determinism", 0.1)], PROBES)

    assert gap.score == pytest.approx(30.0)
    assert gap.coverage.measured == ("determinism", "weak_oracle")
    assert gap.coverage.total == 2


@pytest.mark.parametrize("status", [ProbeStatus.ERROR, ProbeStatus.NOT_APPLICABLE])
def test_a_probe_that_did_not_run_is_excluded_not_scored_zero(status: ProbeStatus) -> None:
    """Scoring a non-measurement as zero would report 'clean' for something never checked."""
    gap = verification_gap([_ok("weak_oracle", 0.6), _skipped("determinism", status)], PROBES)

    assert gap.score == pytest.approx(60.0), "the excluded probe must not drag the mean toward clean"
    assert gap.coverage.measured == ("weak_oracle",)
    assert gap.coverage.total == 2


def test_no_measurement_yields_no_score_rather_than_zero() -> None:
    gap = verification_gap([_skipped("weak_oracle", ProbeStatus.ERROR)], PROBES)

    assert gap.score is None
    assert gap.coverage.measured == ()


# ------------------------------------------------------- the gap is inseparable from coverage


def test_rendering_a_gap_always_states_its_coverage() -> None:
    """A score from 2 probes and a score from 6 are different quantities."""
    rendered = str(verification_gap([_ok("weak_oracle", 0.34), _ok("determinism", 0.0)], PROBES))

    assert "VERIFICATION GAP" in rendered
    assert "coverage" in rendered
    assert "2 of 2 probes" in rendered


def test_an_unmeasured_gap_says_so_rather_than_printing_a_number() -> None:
    rendered = str(verification_gap([_skipped("weak_oracle", ProbeStatus.ERROR)], PROBES))

    assert "not measured" in rendered
    assert "coverage" in rendered


# --------------------------------------------------------------------------- the registry


def test_both_open_probes_are_discoverable_by_entry_point() -> None:
    from bohrin.probes import registry

    ids = {p.id for p in registry.discover()}
    assert {"weak_oracle", "determinism"} <= ids


def test_mutation_operators_are_discoverable_by_entry_point() -> None:
    from bohrin.mutate import discover

    ops = discover()
    assert ops, "no mutation operators registered — weak_oracle cannot function"
    assert all(op.id for op in ops)
    assert all(op.rationale for op in ops), "an operator must explain why its output is wrong"


def test_every_registered_probe_explains_itself() -> None:
    from bohrin.probes import registry

    for probe in registry.discover(include_excluded=True):
        assert len(probe.explain()) > 80, f"{probe.id} needs a real explanation"
        assert probe.family, f"{probe.id} must declare a family"


def test_excluded_probes_are_documented_when_they_exist() -> None:
    """Mirrors the previous codebase's rule: an exclusion needs evidence, not taste."""
    from bohrin.probes.registry import DEFAULT_EXCLUDED, discover

    if DEFAULT_EXCLUDED:
        available = {p.id for p in discover(include_excluded=True)}
        assert available >= DEFAULT_EXCLUDED, "DEFAULT_EXCLUDED names a probe that does not exist"


# ------------------------------------------------------------------------ report contract


async def test_report_serializes_the_gap_with_its_coverage() -> None:
    from bohrin.config import ScanConfig

    results = [await p.run(_fixtures.weak_source(2), ScanConfig(repeats=3)) for p in PROBES]
    report = Report(
        target="./fixture",
        adapter="memory",
        gap=verification_gap(results, PROBES),
        results=tuple(results),
        tasks_total=2,
    )

    blob = json.loads(json.dumps(report.to_dict()))

    assert blob["schema_version"] == REPORT_SCHEMA_VERSION
    assert "coverage" in blob["verification_gap"], "the score must never serialize without coverage"
    assert set(blob["verification_gap"]["coverage"]) == {"measured", "total"}
    assert len(blob["probes"]) == 2
    assert blob["probes"][0]["findings"], "the weak fixture must produce findings in the JSON"


# ------------------------------------------------------- reporting what a bound truncated


def _clean_report(tasks_total: int, corpus_total: int | None) -> Report:
    from bohrin.probes.base import ProbeResult, ProbeStatus

    results = [
        ProbeResult(
            probe_id="weak_oracle",
            status=ProbeStatus.OK,
            sub_score=0.0,
            tasks_probed=tasks_total,
            findings=(),
            detail={"operators": ("identity_return",)},
        )
    ]
    return Report(
        target="./fixture",
        adapter="memory",
        gap=verification_gap(results, [p for p in PROBES if p.id == "weak_oracle"]),
        results=tuple(results),
        tasks_total=tasks_total,
        corpus_total=corpus_total,
    )


def test_an_audit_that_saw_the_whole_taskset_is_not_marked_truncated() -> None:
    assert _clean_report(10, 10).truncated is False
    # An adapter that cannot say how big the corpus is must not imply the audit was partial.
    assert _clean_report(10, None).truncated is False


def test_an_audit_bounded_below_the_corpus_is_marked_truncated() -> None:
    assert _clean_report(10, 541).truncated is True


def test_the_corpus_size_and_truncation_are_serialised() -> None:
    blob = json.loads(json.dumps(_clean_report(10, 541).to_dict()))
    assert blob["tasks_total"] == 10
    assert blob["corpus_total"] == 541
    assert blob["truncated"] is True


def test_a_clean_score_over_a_prefix_says_so() -> None:
    """The failure this prevents was measured, not imagined.

    On a published environment a 10-task bound scored 0 while a 20-task bound scored 50 on
    the same verifier, because the tasks carrying the defect sat at positions 11 and 12.
    A clean score printed without naming the bound invites exactly the wrong conclusion.
    """
    from bohrin.report.tty import _zero_score_caveat

    caveat = _zero_score_caveat(_clean_report(10, 541))
    assert caveat is not None
    assert "first 10 of 541 tasks" in caveat
    assert "prefix rather than a sample" in caveat


def test_a_clean_score_over_the_whole_taskset_does_not_claim_truncation() -> None:
    from bohrin.report.tty import _zero_score_caveat

    caveat = _zero_score_caveat(_clean_report(10, 10))
    assert caveat is not None
    assert "were audited" not in caveat
