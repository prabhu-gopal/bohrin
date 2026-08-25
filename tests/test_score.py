"""The Quality Score: the properties a headline number has to have (docs/02 §5.3).

The score used to aggregate additively — a fixed penalty per cluster, subtracted from 100. That
formula has two defects, and both are tested against here:

1. **It saturated.** At 40 points per dataset-wide HIGH, three of them reached 120 and the score
   pinned at 0. Past that point a merely-bad dataset and a catastrophic one were indistinguishable,
   fixing a finding moved nothing, and the number stopped carrying information exactly when the
   user needed it most. A 20-episode test dataset with 4 HIGHs scored 0/100.
2. **Findings with no measured blast radius were free.** ``frac_episodes`` is 0 when
   ``total_episodes`` is 0, which several dataset-level INTEGRITY checks emit — so a HIGH
   "declared std disagrees by 5×" left a perfect 100 while the report listed a serious defect.

The replacement multiplies: each cluster removes a fraction of what remains. The tests below are
the specification of that behaviour, not a transcription of it — each asserts a property a user
would notice if it broke.
"""

from __future__ import annotations

import itertools

import pytest

import _synth
from bohrin.ir.schema import Family, Severity
from bohrin.report.model import BlastRadius, Cluster, Fix
from bohrin.synth.pipeline import effective_blast, quality_score, score_contributions


def _cluster(
    name: str,
    severity: Severity,
    *,
    n_episodes: int = 20,
    total: int = 20,
    family: Family = Family.STATS,
) -> Cluster:
    return Cluster(
        id=name,
        title=f"{name} title",
        family=family,
        severity=severity,
        priority=1.0,
        mechanism="mechanism",
        fix=Fix(text="fix"),
        blast_radius=BlastRadius(n_episodes=n_episodes, total_episodes=total),
    )


def _n_highs(count: int) -> list[Cluster]:
    return [_cluster(f"d{i}", Severity.HIGH) for i in range(count)]


# ------------------------------------------------------------------------- the basics


def test_a_clean_report_scores_exactly_100() -> None:
    assert quality_score([]) == 100


def test_any_finding_lowers_the_score_below_100() -> None:
    """A "100/100" headline beside a list of defects destroys trust in the number."""
    for severity in (Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO):
        assert quality_score([_cluster("d", severity)]) < 100, f"{severity} left a perfect score"


def test_the_score_stays_in_range() -> None:
    for count in (0, 1, 5, 50, 500):
        assert 0 <= quality_score(_n_highs(count)) <= 100


# --------------------------------------------------------------- the saturation defect


def test_the_score_does_not_saturate() -> None:
    """The core fix: many severe findings must still produce distinguishable scores.

    Under the additive formula every one of these was 0.
    """
    scores = [quality_score(_n_highs(k)) for k in range(3, 11)]
    assert all(s > 0 for s in scores), f"score bottomed out: {scores}"


def test_more_findings_always_score_strictly_lower() -> None:
    """Strict monotonicity — so fixing one finding always visibly moves the number."""
    scores = [quality_score(_n_highs(k)) for k in range(0, 9)]
    for worse, better in zip(scores[1:], scores[:-1], strict=True):
        assert worse < better, f"adding a HIGH did not lower the score: {scores}"


def test_two_badly_broken_datasets_remain_comparable() -> None:
    """The user-facing point of the whole change: ranking still works at the bad end."""
    bad = quality_score(_n_highs(4))
    catastrophic = quality_score(_n_highs(9))
    assert catastrophic < bad
    assert bad - catastrophic >= 5, "the gap is too small to be legible in a headline number"


def test_a_worse_severity_scores_lower_at_equal_blast() -> None:
    high = quality_score([_cluster("d", Severity.HIGH)])
    medium = quality_score([_cluster("d", Severity.MEDIUM)])
    low = quality_score([_cluster("d", Severity.LOW)])
    info = quality_score([_cluster("d", Severity.INFO)])
    assert high < medium < low <= info


def test_a_wider_blast_radius_scores_lower() -> None:
    narrow = quality_score([_cluster("d", Severity.HIGH, n_episodes=2, total=100)])
    wide = quality_score([_cluster("d", Severity.HIGH, n_episodes=90, total=100)])
    assert wide < narrow


def test_the_score_is_independent_of_cluster_order() -> None:
    """Multiplication commutes; the headline must not depend on incidental sort order."""
    clusters = [
        _cluster("a", Severity.HIGH),
        _cluster("b", Severity.MEDIUM, n_episodes=5),
        _cluster("c", Severity.LOW, n_episodes=1),
    ]
    assert quality_score(clusters) == quality_score(list(reversed(clusters)))


def test_a_single_finding_matches_the_previous_formula() -> None:
    """Continuity: the weights are the old point penalties, so one finding is unchanged.

    Worth pinning — it means the change is invisible on the common single-defect report and
    only alters behaviour in the regime where the old formula was broken.
    """
    assert quality_score([_cluster("d", Severity.HIGH)]) == 60
    assert quality_score([_cluster("d", Severity.MEDIUM)]) == 85
    assert quality_score([_cluster("d", Severity.LOW)]) == 95


# ----------------------------------------------------------- the free-finding defect


def test_a_finding_with_no_measured_blast_radius_still_costs() -> None:
    """``BlastRadius()`` means "extent unmeasured", not "affects nothing"."""
    unmeasured = Cluster(
        id="integrity.declared_mismatch",
        title="Declared std disagrees with the data by 5×",
        family=Family.INTEGRITY,
        severity=Severity.HIGH,
        priority=1.0,
        mechanism="stale normalization metadata",
        fix=Fix(text="recompute stats.json"),
    )
    assert quality_score([unmeasured]) == 60, "an unmeasured HIGH was scored as free"
    assert effective_blast(unmeasured) == 1.0


def test_a_tiny_but_severe_finding_moves_the_number() -> None:
    """1 HIGH episode in 1000 is localized, but "flawless" would contradict the report."""
    score = quality_score([_cluster("d", Severity.HIGH, n_episodes=1, total=1000)])
    assert score < 100
    assert score >= 90, "a genuinely localized defect should not read as a broken dataset"


def test_severity_floors_are_ordered() -> None:
    """A HIGH must never be credited less blast than a MEDIUM of the same extent."""
    high = _cluster("d", Severity.HIGH, n_episodes=1, total=1000)
    medium = _cluster("d", Severity.MEDIUM, n_episodes=1, total=1000)
    assert effective_blast(high) > effective_blast(medium)


def test_an_info_only_report_is_capped_below_100() -> None:
    """INFO carries zero weight, so only the cap keeps the headline honest."""
    assert quality_score([_cluster("d", Severity.INFO)]) == 99


# ---------------------------------------------------------------- explainability


def test_contributions_decompose_the_score_exactly() -> None:
    """ "Why is my score 34?" must be answerable arithmetically."""
    clusters = [
        _cluster("a", Severity.HIGH),
        _cluster("b", Severity.MEDIUM, n_episodes=10),
        _cluster("c", Severity.LOW, n_episodes=4),
    ]
    contributions = score_contributions(clusters)
    assert len(contributions) == len(clusters)
    assert contributions[0].before == 100.0
    # Each step hands its remainder to the next, and the last equals the reported score.
    for previous, following in itertools.pairwise(contributions):
        assert following.before == pytest.approx(previous.after)
    assert round(contributions[-1].after) == quality_score(clusters)


def test_contributions_are_ordered_worst_first() -> None:
    clusters = [
        _cluster("small", Severity.LOW, n_episodes=1),
        _cluster("big", Severity.HIGH),
        _cluster("mid", Severity.MEDIUM),
    ]
    ids = [c.cluster_id for c in score_contributions(clusters)]
    assert ids == ["big", "mid", "small"]
    assert score_contributions(clusters)[0].points_lost > 0


def test_contributions_of_a_clean_report_are_empty() -> None:
    assert score_contributions([]) == []


# ----------------------------------------------------------------- end to end


def test_a_clean_dataset_produces_no_clusters_and_would_score_100() -> None:
    """The score is no longer reported (see Report's docstring), so it is exercised here
    against the clusters a real scan produces, which is what it will consume when the
    headline returns."""
    from bohrin.api import scan

    report = scan(_synth.register_memory_dataset(_synth.clean_dataset(n_episodes=16)))
    assert not report.clusters
    assert quality_score(report.clusters) == 100


def test_no_aggregate_score_is_reported() -> None:
    """A 0-100 number implies a calibration against training outcomes that does not exist.

    Pinned as a test because it is the kind of thing that gets helpfully re-added.
    """
    from bohrin.api import scan

    report = scan(_synth.register_memory_dataset(_synth.clean_dataset(n_episodes=8)))
    assert not hasattr(report, "score")
    assert "score" not in report.to_json()


def test_a_defective_dataset_scores_low_but_not_zero() -> None:
    """The regression from the report that started this: a multi-HIGH scan scored 0/100."""
    from bohrin.api import scan

    episodes = _synth.inject_dead_dimension(_synth.clean_dataset(n_episodes=20))
    episodes = _synth.inject_saturation(episodes)
    episodes[3] = _synth.inject_nan(episodes[3])
    episodes[5] = _synth.inject_jump(episodes[5])
    report = scan(_synth.register_memory_dataset(episodes))

    highs = sum(1 for c in report.clusters if c.severity is Severity.HIGH)
    assert highs >= 3, f"fixture did not produce enough HIGHs to test saturation ({highs})"
    score = quality_score(report.clusters)
    assert 0 < score < 60, f"expected a low-but-informative score, got {score}"


def test_adding_a_defect_to_a_real_scan_lowers_the_score() -> None:
    """Monotonicity through the whole pipeline, not just the formula."""
    from bohrin.api import scan

    base = _synth.clean_dataset(n_episodes=20)
    worse = _synth.inject_dead_dimension(base)
    worst = _synth.inject_saturation(worse)

    scores = [quality_score(scan(_synth.register_memory_dataset(eps)).clusters) for eps in (base, worse, worst)]
    assert scores[0] > scores[1] > scores[2], scores
