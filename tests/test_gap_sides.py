"""The two directions of the gap, reported side by side.

A verifier can be wrong by accepting wrong work or by rejecting right work. The headline counts
only what can be scored soundly, so the sides are reported next to it — never folded into it.
"""

from __future__ import annotations

import json
from io import StringIO

from rich.console import Console

import _fixtures
from bohrin.config import ScanConfig
from bohrin.probes.base import Probe, ProbeResult, ProbeStatus
from bohrin.probes.ground_truth_rejected import GroundTruthRejectedProbe
from bohrin.probes.weak_oracle import WeakOracleProbe
from bohrin.report.model import Report
from bohrin.report.tty import render
from bohrin.scoring.gap import verification_gap

CONFIG = ScanConfig(unsafe_local=True)


def _report(results: list[ProbeResult], probes: list[Probe]) -> Report:
    return Report(
        target="./fixture",
        adapter="memory",
        gap=verification_gap(results, probes),
        results=tuple(results),
        tasks_total=3,
    )


async def test_both_sides_are_reported_and_the_headline_is_unchanged() -> None:
    source = _fixtures.broken_baseline_source(3)  # rejects its own answer on every task
    probes: list[Probe] = [WeakOracleProbe(), GroundTruthRejectedProbe()]
    weak = await WeakOracleProbe().run(_fixtures.weak_source(3), CONFIG)
    rejected = await GroundTruthRejectedProbe().run(source, CONFIG)

    gap = verification_gap([weak, rejected], probes)
    sides = {side.name: side for side in gap.sides}

    assert sides["acceptance"].score == 100.0
    assert sides["rejection"].score == 100.0
    assert gap.score == 100.0, "the rejection side must not move the headline"
    alone = verification_gap([weak], [WeakOracleProbe()])
    assert alone.score == gap.score


def test_an_unmeasured_side_is_none_not_clean() -> None:
    probes: list[Probe] = [WeakOracleProbe(), GroundTruthRejectedProbe()]
    results = [
        ProbeResult(probe_id="weak_oracle", status=ProbeStatus.OK, tasks_probed=1, sub_score=0.0),
        ProbeResult(probe_id="ground_truth_rejected", status=ProbeStatus.NOT_APPLICABLE, reason="no answer"),
    ]

    sides = {side.name: side for side in verification_gap(results, probes).sides}

    assert sides["acceptance"].score == 0.0
    assert sides["rejection"].score is None


async def test_the_json_carries_the_sides() -> None:
    probes: list[Probe] = [WeakOracleProbe(), GroundTruthRejectedProbe()]
    results = [await p.run(_fixtures.strict_source(3), CONFIG) for p in probes]

    blob = json.loads(json.dumps(_report(results, probes).to_dict()))

    assert set(blob["verification_gap"]["sides"]) == {"acceptance", "rejection"}
    assert blob["verification_gap"]["sides"]["rejection"]["probes"] == ["ground_truth_rejected"]


async def test_the_terminal_names_the_rejection_side_as_outside_the_gap() -> None:
    probes: list[Probe] = [WeakOracleProbe(), GroundTruthRejectedProbe()]
    results = [await p.run(_fixtures.strict_source(3), CONFIG) for p in probes]
    buffer = StringIO()

    render(_report(results, probes), Console(file=buffer, width=200, no_color=True))

    assert "sides: acceptance 0 / 100 · rejection 0 / 100" in buffer.getvalue()
    assert "not counted in the gap" in buffer.getvalue()
