"""Probe behaviour, from both directions.

The recall tests below (a probe must find a planted defect) matter. The precision tests
matter more: Bohrin's whole value rests on a finding being trustworthy, and a tool that
accuses a correct verifier is worth less than no tool at all.
"""

from __future__ import annotations

import pytest

import _fixtures
from bohrin.config import ScanConfig
from bohrin.ir.evidence import Exploit, Flake
from bohrin.probes.base import ProbeStatus
from bohrin.probes.determinism import DeterminismProbe
from bohrin.probes.weak_oracle import WeakOracleProbe

CFG = ScanConfig(concurrency=4, per_task_timeout=5.0, repeats=5)


# ------------------------------------------------------------------ weak oracle: recall


async def test_weak_oracle_finds_a_verifier_that_accepts_anything() -> None:
    result = await WeakOracleProbe().run(_fixtures.weak_source(3), CFG)

    assert result.status is ProbeStatus.OK
    assert result.findings, "a verifier accepting any non-empty payload must be caught"
    assert result.sub_score == 1.0, "every task is compromised, so the sub-score is 1.0"
    assert all(isinstance(f, Exploit) for f in result.findings)


async def test_every_reported_exploit_carries_a_wrongness_ground() -> None:
    """The invariant the whole probe rests on: no ground, no finding."""
    result = await WeakOracleProbe().run(_fixtures.weak_source(3), CFG)

    for finding in result.findings:
        assert isinstance(finding, Exploit)
        assert finding.candidate.known_wrong
        assert finding.candidate.ground is not None
        assert finding.repro


# --------------------------------------------------------------- weak oracle: precision


async def test_weak_oracle_reports_nothing_against_a_strict_verifier() -> None:
    """The false-accusation guard. If this ever fails, the product is broken."""
    result = await WeakOracleProbe().run(_fixtures.strict_source(3), CFG)

    assert result.status is ProbeStatus.OK
    assert result.findings == (), f"falsely accused a correct verifier: {result.findings}"
    assert result.unverified == ()
    assert result.sub_score == 0.0


async def test_constant_operator_never_submits_a_literal_that_is_the_answer() -> None:
    """An equivalent mutant must be filtered before submission, not reported."""
    from bohrin.ir.task import Task
    from bohrin.mutate.operators import ConstantReturn

    task = Task(id="t", prompt="Return zero.", reference="0", reward_fns=("exact",))
    payloads = [c.payload for c in ConstantReturn().apply(task)]

    assert "0" not in payloads, "emitting the reference answer as a 'wrong' candidate is a false accusation"
    assert payloads, "other literals are still legitimate candidates"


async def test_operators_decline_when_there_is_no_reference() -> None:
    """Without a reference the differential ground is unavailable; guessing is not allowed."""
    from bohrin.ir.task import Task
    from bohrin.mutate.operators import ConstantReturn, DropSideEffect

    task = Task(id="t", prompt="Do something.", reference=None, reward_fns=("exact",))

    assert list(ConstantReturn().apply(task)) == []
    assert list(DropSideEffect().apply(task)) == []


# ------------------------------------------------------------------- determinism probe


async def test_determinism_finds_a_flaky_verifier() -> None:
    result = await DeterminismProbe().run(_fixtures.flaky_source(3), CFG)

    assert result.status is ProbeStatus.OK
    assert len(result.findings) == 1
    flake = result.findings[0]
    assert isinstance(flake, Flake)
    assert flake.task_id == "task-1"
    assert flake.spread > 0


async def test_determinism_reports_nothing_against_a_stable_verifier() -> None:
    result = await DeterminismProbe().run(_fixtures.strict_source(3), CFG)

    assert result.status is ProbeStatus.OK
    assert result.findings == ()
    assert result.sub_score == 0.0


async def test_determinism_never_claims_an_exploit() -> None:
    """This probe measures reliability, not correctness, and must not imply otherwise."""
    result = await DeterminismProbe().run(_fixtures.flaky_source(3), CFG)

    assert all(isinstance(f, Flake) for f in result.findings)


async def test_determinism_needs_at_least_two_repeats() -> None:
    result = await DeterminismProbe().run(_fixtures.flaky_source(2), ScanConfig(repeats=1))

    assert result.status is ProbeStatus.NOT_APPLICABLE
    assert result.sub_score is None
    assert "2" in result.reason


# --------------------------------------------------------------------------- robustness


async def test_a_verifier_that_raises_does_not_abandon_the_audit() -> None:
    result = await DeterminismProbe().run(_fixtures.exploding_source(2), CFG)

    assert result.status is ProbeStatus.ERROR
    assert result.sub_score is None, "an errored probe must not be scored"
    assert "failed" in result.reason


async def test_empty_taskset_is_not_applicable_not_clean() -> None:
    from bohrin.adapters.memory import MemorySource

    empty = MemorySource([], lambda _t, _p: 1.0)

    for probe in (WeakOracleProbe(), DeterminismProbe()):
        result = await probe.run(empty, CFG)
        assert result.status is ProbeStatus.NOT_APPLICABLE
        assert result.sub_score is None, "no tasks measured must never read as a clean verifier"


def test_probe_result_rejects_ok_without_a_score() -> None:
    from bohrin.probes.base import ProbeResult

    with pytest.raises(ValueError, match="without a sub_score"):
        ProbeResult(probe_id="x", status=ProbeStatus.OK)

    with pytest.raises(ValueError, match="with a sub_score"):
        ProbeResult(probe_id="x", status=ProbeStatus.ERROR, sub_score=0.0)
