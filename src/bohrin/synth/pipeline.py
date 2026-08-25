"""Stage ⑤ — Synthesize: cluster, rank, score (docs/02 §5).

Raw findings are noisy; one root cause can trip several detectors across many episodes.
This stage turns findings into a short, ranked, deterministic story and a single headline
Quality Score. P0 clusters conservatively (one cluster per detector id); P2 adds
root-cause grouping across families. The score formula is intentionally transparent — a
documented, size-normalized rollup, so the number is explainable (docs/02 §5.3).

**On the score formula.** It aggregates *multiplicatively*, not additively, and that is the
whole design. The original version subtracted a fixed penalty per cluster, which meant three
dataset-wide HIGHs summed to 120 points and pinned the score at 0 — after which nothing was
distinguishable. A headline number that bottoms out cannot rank a merely-bad dataset against a
catastrophic one, cannot show progress as a user fixes findings one at a time, and teaches
users to stop reading it. Every finding now removes a *fraction* of what is left, so the score
descends towards 0 without ever arriving and stays strictly monotone in the findings.
"""

from __future__ import annotations

from dataclasses import dataclass

from bohrin.ir.schema import Severity
from bohrin.report.model import BlastRadius, Cluster, Finding

#: Fraction of the *remaining* score one cluster removes at full blast radius. Transparent by
#: design — :func:`score_contributions` prints exactly this arithmetic per cluster.
#:
#: The values are the old point penalties read as fractions, so a dataset with a single
#: dataset-wide finding scores exactly what it always did (one HIGH → 60). They only diverge
#: once findings accumulate, which is precisely where the additive version broke down.
_SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.INFO: 0.0,
    Severity.LOW: 0.05,
    Severity.MEDIUM: 0.15,
    Severity.HIGH: 0.40,
}

#: Minimum blast radius credited to a finding of each severity.
#:
#: Two cases need this. A finding that reports no blast radius at all (``BlastRadius()``, which
#: several dataset-level INTEGRITY checks emit) had ``frac_episodes == 0`` and therefore cost
#: *nothing* — a HIGH "declared std disagrees by 5×" left the score at a perfect 100, which
#: reads as a contradiction and quietly hid the finding from the headline. And a HIGH affecting
#: 1 episode in 1000 is genuinely localized but should still move the number, or the score
#: implies "flawless" while the report lists a serious defect.
_SEVERITY_FLOOR: dict[Severity, float] = {
    Severity.INFO: 0.0,
    Severity.LOW: 0.02,
    Severity.MEDIUM: 0.05,
    Severity.HIGH: 0.10,
}


def _priority(severity: Severity, blast: BlastRadius, confidence: float, policy_weight: float) -> float:
    """`severity × blast × policy_weight × confidence` (docs/02 §5.2)."""
    return (severity.rank + 1) * (0.5 + blast.frac_episodes) * policy_weight * confidence


def _aggregate_blast(findings: list[Finding], total_episodes: int) -> BlastRadius:
    n = max((f.blast_radius.n_episodes for f in findings), default=0)
    frac_steps = max((f.blast_radius.frac_steps for f in findings), default=0.0)
    return BlastRadius(n_episodes=n, total_episodes=total_episodes, frac_steps=frac_steps)


def cluster_findings(findings: list[Finding], total_episodes: int) -> list[Cluster]:
    """Group findings by detector id into ranked clusters (P0 clustering)."""
    by_detector: dict[str, list[Finding]] = {}
    for f in findings:
        by_detector.setdefault(f.detector_id, []).append(f)

    clusters: list[Cluster] = []
    for detector_id, group in by_detector.items():
        headline = max(group, key=lambda f: (f.severity.rank, f.confidence))
        blast = _aggregate_blast(group, total_episodes)
        confidence = max(f.confidence for f in group)
        clusters.append(
            Cluster(
                id=detector_id,
                title=headline.title,
                family=headline.family,
                severity=headline.severity,
                priority=_priority(headline.severity, blast, confidence, policy_weight=1.0),
                mechanism=headline.mechanism,
                fix=headline.fix,
                blast_radius=blast,
                findings=sorted(group, key=lambda f: (-f.severity.rank, f.title)),
            )
        )

    # Deterministic order: highest priority first, id as the stable tie-breaker.
    clusters.sort(key=lambda c: (-c.priority, c.id))
    return clusters


@dataclass(frozen=True, slots=True)
class ScoreContribution:
    """One cluster's effect on the Quality Score — the arithmetic, itemized."""

    cluster_id: str
    severity: Severity
    #: Blast radius actually used, after applying the severity floor.
    blast: float
    #: Fraction of the score remaining at this point that the cluster removes.
    impact: float
    #: Score before and after this cluster is applied (both 0–100).
    before: float
    after: float

    @property
    def points_lost(self) -> float:
        """Points this cluster removed, in the order clusters were applied."""
        return self.before - self.after


def effective_blast(cluster: Cluster) -> float:
    """Blast radius used for scoring: the finest measure the detector reported, severity-floored.

    A cluster that reports no blast radius (``total_episodes == 0``) is not evidence of a
    *small* problem — it is a finding whose extent was never measured, which several
    dataset-level checks legitimately do. Treating that as zero made such findings free.

    **Why the step fraction wins when a detector measured one.** Episode count is a coarse
    proxy: a detector whose unit is the individual transition contaminates an episode's count
    with a single bad step, and for a diffuse defect that rounds up to "every episode". Measured
    on ``lerobot/pusht``, ``dynamics.inverse_residual`` flagged 2.0 % of transitions (513 of
    25 238) spread evenly, which put at least one in all 206 episodes and scored as blast 1.0 —
    a 100 % HIGH penalty for a 2 % defect. That is not a threshold being wrong; it is arithmetic,
    since with a 2 % per-step rate and ~120 steps an episode, P(at least one) ≈ 91 %. Both
    numbers describe the same data, but only the step fraction separates "a few bad transitions
    everywhere" from "every step of every episode is broken", so it is the honest extent.
    """
    blast = cluster.blast_radius
    episodes = blast.frac_episodes if blast.total_episodes else 1.0
    measured = blast.frac_steps if blast.frac_steps > 0.0 else episodes
    return max(min(measured, 1.0), _SEVERITY_FLOOR[cluster.severity])


def score_contributions(clusters: list[Cluster]) -> list[ScoreContribution]:
    """Itemize how each cluster moved the Quality Score, worst-first.

    This is the answer to "why is my score 34?", and it exists because a headline number
    nobody can decompose is a number nobody trusts.
    """
    ordered = sorted(clusters, key=lambda c: (-_SEVERITY_WEIGHT[c.severity] * effective_blast(c), c.id))
    remaining = 100.0
    out: list[ScoreContribution] = []
    for c in ordered:
        blast = effective_blast(c)
        impact = _SEVERITY_WEIGHT[c.severity] * blast
        before = remaining
        remaining = remaining * (1.0 - impact)
        out.append(
            ScoreContribution(
                cluster_id=c.id,
                severity=c.severity,
                blast=blast,
                impact=impact,
                before=before,
                after=remaining,
            )
        )
    return out


def quality_score(clusters: list[Cluster]) -> int:
    """A transparent 0–100 rollup: each finding removes a fraction of what remains.

    ``100 · Π (1 − weightₛ · blast)`` over clusters. Properties this buys, all asserted in
    ``tests/test_score.py``:

    * **A clean dataset scores exactly 100**, and any finding strictly lowers it.
    * **It never saturates.** Ten dataset-wide HIGHs score 1, not 0, so two badly-broken
      datasets remain comparable and fixing one finding always visibly moves the number.
    * **Order-independent.** Multiplication commutes, so the score does not depend on how
      clusters happened to be sorted.
    * **Rounding cannot fake a perfect score**: a non-empty report is capped at 99, because
      "100/100" beside a list of defects destroys trust in the number more than any
      inaccuracy would.
    """
    if not clusters:
        return 100
    remaining = 100.0
    for c in clusters:
        remaining *= 1.0 - _SEVERITY_WEIGHT[c.severity] * effective_blast(c)
    # INFO-only reports have zero weight and would round back to 100; cap so the headline
    # never contradicts the body. Floor at 0 for the degenerate weight==1 case.
    return int(min(99, max(0, round(remaining))))


def synthesize(findings: list[Finding], total_episodes: int) -> list[Cluster]:
    """Cluster + rank in one call.

    Deliberately does **not** return :func:`quality_score`. That function is still here and
    still tested, because the arithmetic is sound and we will want it — but a headline
    number is a claim about how much a defect costs a trained policy, and nothing in this
    tool measures that yet. It ships when a calibration corpus can back it.
    """
    return cluster_findings(findings, total_episodes)
