"""The Verification Gap: the arithmetic, the coverage it carries, and its two sides."""

from __future__ import annotations

import pytest

from bohrin.ir.result import ProbeResult, ProbeStatus
from bohrin.scoring.gap import FAMILIES, WEIGHTS, verification_gap


def _ok(pid: str, score: float) -> ProbeResult:
    return ProbeResult(probe_id=pid, status=ProbeStatus.OK, sub_score=score, tasks_probed=10)


def _skipped(pid: str, status: ProbeStatus) -> ProbeResult:
    return ProbeResult(probe_id=pid, status=status, reason="fixture")


# ------------------------------------------------------------------- the arithmetic


def test_gap_is_the_weighted_mean_scaled_to_100() -> None:
    gap = verification_gap([_ok("weak_oracle", 0.5), _ok("determinism", 0.1)])

    assert gap.score == pytest.approx(30.0)
    assert gap.coverage.measured == ("determinism", "weak_oracle")
    assert gap.coverage.total == 2


@pytest.mark.parametrize("status", [ProbeStatus.ERROR, ProbeStatus.NOT_APPLICABLE])
def test_a_check_that_did_not_run_is_excluded_not_scored_zero(status: ProbeStatus) -> None:
    """Scoring a non-measurement as zero would report 'clean' for something never checked."""
    gap = verification_gap([_ok("weak_oracle", 0.6), _skipped("determinism", status)])

    assert gap.score == pytest.approx(60.0)
    assert gap.coverage.measured == ("weak_oracle",)
    assert gap.coverage.total == 2


def test_no_measurement_yields_no_score_rather_than_zero() -> None:
    gap = verification_gap([_skipped("weak_oracle", ProbeStatus.ERROR)])

    assert gap.score is None
    assert gap.coverage.measured == ()


def test_the_published_weights_keep_the_lead_only_checks_out_of_the_headline() -> None:
    assert WEIGHTS["weak_oracle"] == WEIGHTS["determinism"] == 1.0
    assert WEIGHTS["ground_truth_rejected"] == WEIGHTS["answer_leakage"] == 0.0
    assert set(WEIGHTS) == set(FAMILIES)


def test_an_unnamed_check_takes_the_default_weight() -> None:
    gap = verification_gap([_ok("weak_oracle", 1.0), _ok("third_party", 0.0)])
    assert gap.score == pytest.approx(50.0)


def test_a_check_result_cannot_claim_ok_without_a_score() -> None:
    with pytest.raises(ValueError, match="without a sub_score"):
        ProbeResult(probe_id="x", status=ProbeStatus.OK)
    with pytest.raises(ValueError, match="with a sub_score"):
        ProbeResult(probe_id="x", status=ProbeStatus.ERROR, sub_score=0.0)


# ----------------------------------------------------- the gap is inseparable from coverage


def test_rendering_a_gap_always_states_its_coverage() -> None:
    rendered = str(verification_gap([_ok("weak_oracle", 0.34), _ok("determinism", 0.0)]))

    assert "VERIFICATION GAP" in rendered
    assert "2 of 2 probes" in rendered


def test_an_unmeasured_gap_says_so_rather_than_printing_a_number() -> None:
    rendered = str(verification_gap([_skipped("weak_oracle", ProbeStatus.ERROR)]))

    assert "not measured" in rendered
    assert "coverage" in rendered


# --------------------------------------------------------------------------- two sides


def test_both_sides_are_reported_and_the_headline_is_unchanged() -> None:
    gap = verification_gap([_ok("weak_oracle", 1.0), _ok("ground_truth_rejected", 1.0)])
    sides = {side.name: side for side in gap.sides}

    assert sides["acceptance"].score == 100.0
    assert sides["rejection"].score == 100.0
    assert gap.score == 100.0
    assert verification_gap([_ok("weak_oracle", 1.0)]).score == gap.score, "the rejection side moved the headline"


def test_a_lead_only_check_never_moves_the_headline() -> None:
    clean = verification_gap([_ok("weak_oracle", 0.0), _ok("answer_leakage", 1.0), _ok("ground_truth_rejected", 1.0)])
    assert clean.score == 0.0


def test_an_unmeasured_side_is_none_not_clean() -> None:
    results = [_ok("weak_oracle", 0.0), _skipped("ground_truth_rejected", ProbeStatus.NOT_APPLICABLE)]
    sides = {side.name: side for side in verification_gap(results).sides}

    assert sides["acceptance"].score == 0.0
    assert sides["rejection"].score is None
