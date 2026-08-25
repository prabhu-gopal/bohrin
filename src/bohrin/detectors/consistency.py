"""Family F — CONSISTENCY: do the demonstrations agree with each other? (docs/04 §F).

Implements the *Consistency Matters* cross-demo method: compute a metric vector per demo
(jerk, path length, duration, mean speed), then look at how those vary *across* demos and
split consistent from inconsistent. Mixing skilled and unskilled or multi-operator styles
injects heterogeneous targets that a final imitation objective struggles to fit.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from bohrin._arrays import BoolArray, FloatArray
from bohrin.analysis.embeddings import trajectory
from bohrin.analysis.shapes import dtw_distance, path_length, resample
from bohrin.detectors._common import blast_over, dataset_provenance, gate_scores, make_finding
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.ir.episode import Episode
from bohrin.ir.schema import Family, Severity
from bohrin.report.model import Evidence, Finding, Locus

_EPS = 1e-12
_SILHOUETTE = 0.65  # a decisive two-cluster split of demonstration styles
_DTW_Z = 4.0  # robust-z above which a demo is a trajectory outlier
_DTW_RATIO = 2.0  # …and it must also be this many times the typical distance
_DURATION_CV = 0.6  # robust coefficient of variation of episode length


def _metric_vectors(episodes: Sequence[Episode]) -> FloatArray:
    """Per-demo metric vector: path length, duration, mean speed, jerk energy."""
    rows: list[FloatArray] = []
    for ep in episodes:
        traj = trajectory(ep)
        length = float(traj.shape[0])
        path = path_length(traj)
        speed = path / length if length else 0.0
        jerk = float(np.mean(np.sum(np.diff(traj, n=3, axis=0) ** 2, axis=1))) if traj.shape[0] >= 4 else 0.0
        rows.append(np.array([path, length, speed, jerk], dtype=np.float64))
    return np.vstack(rows) if rows else np.empty((0, 4), dtype=np.float64)


class OperatorStyleDetector(Detector):
    """Flags a dataset that splits into two distinct demonstration styles."""

    id = "consistency.operator_style"
    family = Family.CONSISTENCY
    requires = Requirements(min_episodes=10)
    description = "Detects two distinct demonstration styles (e.g. fast/loose vs slow/precise) mixed in one dataset."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        episodes = ctx.episodes
        if len(episodes) < self.requires.min_episodes:
            return []
        metrics = _metric_vectors(episodes)
        # KMeans raises on NaN/inf. Episodes and metric rows are filtered together because
        # `labels[i]` is reported as `episodes[i]` — renumbering one alone would name the
        # wrong episode in the finding.
        finite: BoolArray = np.asarray(np.isfinite(metrics).all(axis=1), dtype=np.bool_)
        if not bool(finite.all()):
            episodes = [ep for ep, ok in zip(episodes, finite.tolist(), strict=True) if ok]
            metrics = metrics[finite]
            if len(episodes) < self.requires.min_episodes:
                return []
        std = metrics.std(axis=0)
        std[std < _EPS] = 1.0
        scaled = (metrics - metrics.mean(axis=0)) / std
        labels = KMeans(n_clusters=2, n_init=10, random_state=0).fit_predict(scaled)
        if len(set(labels.tolist())) < 2:
            return []
        score = float(silhouette_score(scaled, labels))
        if score < _SILHOUETTE:
            return []
        minority = int(np.argmin(np.bincount(labels)))
        members = [episodes[i].episode_id for i in range(len(episodes)) if labels[i] == minority]
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=float(min(1.0, score)),
                title=(
                    f"Demonstrations split into two distinct styles ({len(members)} vs {len(episodes) - len(members)})"
                ),
                mechanism=(
                    "Mixing demonstration styles — different operators, or the same operator "
                    "before and after practice — injects heterogeneous targets. Heterogeneity "
                    "helps pre-training but hurts the final imitation fit."
                ),
                fix_text="Consider training on the more precise cluster, or condition on the operator.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(metrics={"silhouette": score}, thresholds={"silhouette": _SILHOUETTE}),
                locus=Locus(episodes=members[:50]),
                blast=blast_over(len(members), ctx.profile.n_episodes),
            )
        ]


class TrajectoryAlignmentDetector(Detector):
    """Flags demonstrations that are DTW outliers versus the consensus."""

    id = "consistency.trajectory_alignment"
    family = Family.CONSISTENCY
    requires = Requirements(min_episodes=8)
    description = "Detects outlier demonstrations whose trajectory disagrees with the consensus (possible mislabels)."

    _MAX_EPISODES = 40  # bound the O(n²) DTW matrix

    def _consensus_distances(self, ctx: AnalysisContext) -> FloatArray:
        """Median DTW distance from each demo to all the others.

        The pairwise matrix is filled from its **upper triangle only**. DTW with a symmetric
        step pattern satisfies ``d(i, j) == d(j, i)``, so the original nested comprehension
        computed every pair exactly twice — a straight 2× on the battery's hottest detector.
        """
        episodes = list(ctx.episodes)[: self._MAX_EPISODES]
        resampled = [resample(trajectory(ep), 24) for ep in episodes]
        n = len(resampled)
        if n < 2:
            return np.zeros(n, dtype=np.float64)
        matrix = np.zeros((n, n), dtype=np.float64)
        for i in range(n):
            for j in range(i + 1, n):
                matrix[i, j] = matrix[j, i] = dtw_distance(resampled[i], resampled[j])
        # Median over the others: mask the self-distance rather than including a spurious 0.
        off_diagonal = ~np.eye(n, dtype=bool)
        return np.asarray(np.median(matrix[off_diagonal].reshape(n, n - 1), axis=1), dtype=np.float64)

    def score_units(self, ctx: AnalysisContext) -> FloatArray | None:
        """Per-demo median DTW distance to the others — the quantity :meth:`run` gates on."""
        if len(ctx.episodes) < 2:
            return None
        return self._consensus_distances(ctx)

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        episodes = list(ctx.episodes)[: self._MAX_EPISODES]
        if len(episodes) < self.requires.min_episodes:
            return []
        mean_dist = self._consensus_distances(ctx)
        # Two hurdles: a statistical outlier AND a meaningful absolute gap. On a set of
        # near-identical demos the spread is ~0, so a purely relative rule would turn pure
        # numerical noise into "outliers" — the ratio floor is what prevents that.
        typical = float(np.median(mean_dist))
        eligible: BoolArray = mean_dist > _DTW_RATIO * max(typical, _EPS)
        decision = gate_scores(ctx, self, mean_dist, fallback_z=_DTW_Z, eligible=eligible)
        if not decision.fired:
            return []
        flagged = list(decision.flagged)
        ep_ids = [episodes[i].episode_id for i in flagged]
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=decision.worst_confidence,
                title=f"{len(flagged)} demonstration(s) disagree with the consensus trajectory",
                mechanism=(
                    "An outlier demonstration — a different strategy, a mislabeled task, or an "
                    "error — pulls the policy away from the behaviour the rest of the data teaches."
                ),
                fix_text="Review the flagged episodes; drop errors or relabel them if they are a different task.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={"worst_dtw_distance": float(mean_dist[decision.worst]), **decision.evidence_metrics()},
                    thresholds={"dtw_ratio": _DTW_RATIO, **decision.evidence_thresholds()},
                    notes=decision.note(),
                ),
                locus=Locus(episodes=ep_ids[:50]),
                blast=blast_over(len(flagged), ctx.profile.n_episodes),
            )
        ]


class DurationVarianceDetector(Detector):
    """Flags wildly inconsistent episode durations, which complicate fixed-horizon chunking."""

    id = "consistency.duration_variance"
    family = Family.CONSISTENCY
    requires = Requirements(min_episodes=8)
    description = "Detects inconsistent demonstration pacing, which complicates fixed-horizon action chunking."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        lengths = np.asarray(ctx.profile.episode_lengths, dtype=np.float64)
        if lengths.size < self.requires.min_episodes:
            return []
        median = float(np.median(lengths))
        if median <= _EPS:
            return []
        mad = float(np.median(np.abs(lengths - median)))
        cv = 1.4826 * mad / median
        if cv < _DURATION_CV:
            return []
        return [
            make_finding(
                self,
                severity=Severity.LOW,
                confidence=float(min(1.0, cv / (2 * _DURATION_CV))),
                title=f"Episode durations vary widely ({int(lengths.min())}–{int(lengths.max())} steps)",
                mechanism=(
                    "Wildly varying pacing for the same task complicates fixed-horizon action "
                    "chunking (ACT) and makes the temporal structure harder to learn."
                ),
                fix_text="Standardize the demonstration pacing, or trim idle lead-in/lead-out.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={"robust_cv": cv, "median_length": median},
                    thresholds={"robust_cv": _DURATION_CV},
                ),
                blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes),
            )
        ]
