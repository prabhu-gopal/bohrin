"""Family A — INTEGRITY: is the data even well-formed? (docs/04 §A).

Cheap, run always, gate the rest — a broken file makes every other finding noise. These
checks report hard defects (NaN, shape mismatch, time gaps, duplicates, truncation, stale
declared stats), so most emit at full confidence rather than a calibrated p-value.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

import numpy as np

from bohrin._arrays import BoolArray, FloatArray
from bohrin.detectors._common import (
    blast_over,
    dataset_provenance,
    make_finding,
)
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.ir.episode import Episode
from bohrin.ir.schema import Family, FeatureStats, Severity
from bohrin.report.model import Evidence, Finding, Locus

if TYPE_CHECKING:
    from bohrin.ir.schema import PolicyProfile
    from bohrin.profile.dataset_profile import DatasetProfile

_PROPRIO_HINT_KEYS = ("observation.state", "proprio", "state", "observation.proprio")


class NanInfDetector(Detector):
    """Flags NaN / ±Inf in action, proprio, or timestamp — training-breaking."""

    id = "integrity.nan_inf"
    family = Family.INTEGRITY
    description = "Detects NaN or ±Inf values, which propagate into the loss and break training."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        bad_episodes: list[str] = []
        bad_dims: set[int] = set()
        for ep in ctx.episodes:
            arrays = [ep.steps.action, ep.steps.proprio, ep.steps.timestamp]
            episode_bad = False
            for arr in arrays:
                if arr is None:
                    continue
                mask = ~np.isfinite(np.asarray(arr, dtype=np.float64))
                if mask.any():
                    episode_bad = True
                    if mask.ndim == 2:
                        bad_dims.update(int(d) for d in np.unique(np.nonzero(mask)[1]))
            if episode_bad:
                bad_episodes.append(ep.episode_id)
        if not bad_episodes:
            return []
        total = ctx.profile.n_episodes
        return [
            make_finding(
                self,
                severity=Severity.HIGH,
                confidence=1.0,
                title=f"NaN/Inf values in {len(bad_episodes)} episode(s)",
                mechanism=(
                    "NaNs and infinities propagate through the loss and either diverge "
                    "training or silently zero out gradients. The affected rows are unusable."
                ),
                fix_text=(
                    "Drop or repair the affected steps before training; check the recording pipeline for sensor faults."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(metrics={"n_episodes": float(len(bad_episodes))}),
                locus=Locus(episodes=bad_episodes[:50], dimensions=sorted(bad_dims)),
                blast=blast_over(len(bad_episodes), total),
                fix_machine={"action": "drop_nonfinite_steps"},
            )
        ]


class ShapeDtypeDetector(Detector):
    """Flags episodes whose action/proprio dimensionality disagrees with the dataset schema."""

    id = "integrity.shape_dtype"
    family = Family.INTEGRITY
    description = "Detects ragged or mismatched array shapes across episodes (a mis-loaded batch or concat bug)."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        schema = ctx.schema
        action_bad: list[str] = []
        proprio_bad: list[str] = []
        for ep in ctx.episodes:
            if ep.steps.action_dim != schema.action_dim:
                action_bad.append(ep.episode_id)
            proprio = ep.steps.proprio
            if schema.proprio_dim is not None and proprio is not None and int(proprio.shape[1]) != schema.proprio_dim:
                proprio_bad.append(ep.episode_id)
        findings: list[Finding] = []
        total = ctx.profile.n_episodes
        if action_bad:
            findings.append(
                make_finding(
                    self,
                    severity=Severity.HIGH,
                    confidence=1.0,
                    title=f"{len(action_bad)} episode(s) have an action dim ≠ {schema.action_dim}",
                    mechanism=(
                        "A stray dimensionality among otherwise-uniform episodes means a "
                        "silently mis-loaded batch or a concatenation bug; the model trains "
                        "on garbage rows."
                    ),
                    fix_text="Re-export the offending episodes with the correct action dimensionality.",
                    provenance=dataset_provenance(ctx),
                    locus=Locus(episodes=action_bad[:50]),
                    blast=blast_over(len(action_bad), total),
                    evidence=Evidence(metrics={"expected_action_dim": float(schema.action_dim)}),
                )
            )
        if proprio_bad:
            findings.append(
                make_finding(
                    self,
                    severity=Severity.HIGH,
                    confidence=1.0,
                    title=f"{len(proprio_bad)} episode(s) have a mismatched proprio dim",
                    mechanism="Inconsistent proprio shape breaks batching and silently truncates or pads state.",
                    fix_text="Align proprioception dimensionality across all episodes.",
                    provenance=dataset_provenance(ctx),
                    locus=Locus(episodes=proprio_bad[:50]),
                    blast=blast_over(len(proprio_bad), total),
                )
            )
        return findings


class TimestampRegularityDetector(Detector):
    """Flags time gaps, duplicate timestamps, and non-monotonic time (docs/04 §A)."""

    id = "integrity.timestamp_regularity"
    family = Family.INTEGRITY
    requires = Requirements(needs_timestamps=True)
    description = "Detects irregular control timing (gaps, duplicates, non-monotonic time) that corrupts derivatives."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        offenders: list[str] = []
        worst_gap = 0.0
        non_monotonic = 0
        for ep in ctx.episodes:
            ts = ep.steps.timestamp
            if ts is None or ts.shape[0] < 2:
                continue
            dt = np.diff(np.asarray(ts, dtype=np.float64))
            if np.any(dt <= 0.0):
                non_monotonic += 1
                offenders.append(ep.episode_id)
                continue
            median_dt = float(np.median(dt))
            if median_dt <= 0:
                continue
            gap_ratio = float(dt.max() / median_dt)
            if gap_ratio > 3.0:  # a step ≥ 3× the median interval is a dropped-frame gap
                worst_gap = max(worst_gap, gap_ratio)
                offenders.append(ep.episode_id)
        if not offenders:
            return []
        total = ctx.profile.n_episodes
        severity = Severity.HIGH if non_monotonic else Severity.MEDIUM
        return [
            make_finding(
                self,
                severity=severity,
                confidence=1.0,
                title=f"Irregular timing in {len(offenders)} episode(s)",
                mechanism=(
                    "Irregular Δt corrupts every velocity/jerk feature and any fixed-horizon "
                    "action chunk (ACT): the model learns time-inconsistent dynamics. "
                    "Non-monotonic time indicates a recording or stitching bug."
                ),
                fix_text="Resample to a fixed control rate or drop episodes with dropped/duplicated frames.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "worst_gap_ratio": worst_gap,
                        "non_monotonic_episodes": float(non_monotonic),
                    },
                    thresholds={"gap_ratio": 3.0},
                ),
                locus=Locus(episodes=offenders[:50]),
                blast=blast_over(len(offenders), total),
            )
        ]


class DuplicateFramesDetector(Detector):
    """Flags long runs of consecutive identical (state, action) rows — a stuck sensor/pause."""

    id = "integrity.duplicate_frames"
    family = Family.INTEGRITY
    description = "Detects consecutive identical frames (sensor freeze or paused recording) that inflate the data."

    _MIN_RUN = 10  # consecutive identical rows before it's suspicious

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        offenders: list[str] = []
        longest = 0
        for ep in ctx.episodes:
            action = np.asarray(ep.steps.action, dtype=np.float64)
            proprio = ep.steps.proprio
            combined = action if proprio is None else np.hstack([action, np.asarray(proprio, dtype=np.float64)])
            if combined.shape[0] < 2:
                continue
            identical = np.all(combined[1:] == combined[:-1], axis=1)
            run = _longest_run(identical)
            if run >= self._MIN_RUN:
                offenders.append(ep.episode_id)
                longest = max(longest, run)
        if not offenders:
            return []
        total = ctx.profile.n_episodes
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=1.0,
                title=f"Frozen/duplicated frames in {len(offenders)} episode(s)",
                mechanism=(
                    "Long runs of identical state+action are zero-information rows from a "
                    "stuck sensor or paused recording; they bias the statistics and the "
                    "marginal action toward 'do nothing'."
                ),
                fix_text="Trim the frozen segments; check for a sensor that stalls during collection.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={"longest_run": float(longest)},
                    thresholds={"min_run": float(self._MIN_RUN)},
                ),
                locus=Locus(episodes=offenders[:50]),
                blast=blast_over(len(offenders), total),
            )
        ]


class TruncatedEpisodesDetector(Detector):
    """Flags episodes far shorter than the dataset's typical length — aborted demos."""

    id = "integrity.truncated_episodes"
    family = Family.INTEGRITY
    requires = Requirements(min_episodes=4)
    description = "Detects abnormally short episodes (aborted demonstrations) relative to the median length."

    _FRAC = 0.3  # shorter than 30% of the median length is suspicious

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        lengths = np.asarray(ctx.profile.episode_lengths, dtype=np.float64)
        if lengths.size < self.requires.min_episodes:
            return []
        median = float(np.median(lengths))
        if median <= 0:
            return []
        cutoff = max(3.0, self._FRAC * median)
        idx = np.nonzero(lengths < cutoff)[0]
        if idx.size == 0:
            return []
        episodes = [ctx.episodes[int(i)].episode_id for i in idx if int(i) < len(ctx.episodes)]
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=1.0,
                title=f"{idx.size} episode(s) end far below the median length",
                mechanism=(
                    "Truncated or aborted demonstrations teach the policy to stop early, before the task is complete."
                ),
                fix_text="Review the short episodes; drop aborted demos or re-record them to completion.",
                provenance=dataset_provenance(ctx),
                evidence=Evidence(metrics={"median_length": median, "cutoff": cutoff, "n_short": float(idx.size)}),
                locus=Locus(episodes=episodes[:50]),
                blast=blast_over(int(idx.size), ctx.profile.n_episodes),
            )
        ]


class DeclaredMismatchDetector(Detector):
    """Compares declared normalization stats (stats.json) to what we measured (docs/04 §A)."""

    id = "integrity.declared_mismatch"
    family = Family.INTEGRITY
    description = "Detects stale/incorrect declared normalization stats that would be baked into the model."

    _RATIO = 2.0  # declared vs measured std disagreeing by ≥ 2× is stale metadata

    def applicable(self, profile: DatasetProfile, policy: PolicyProfile | None) -> bool:
        return super().applicable(profile, policy) and bool(profile.hints.declared_stats)

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        declared = ctx.profile.hints.declared_stats
        if not declared:
            return []
        findings: list[Finding] = []
        checks = [("action", ctx.profile.action)]
        if ctx.profile.proprio is not None:
            for key in _PROPRIO_HINT_KEYS:
                if key in declared:
                    checks.append((key, ctx.profile.proprio))
                    break
        for key, measured in checks:
            stat = declared.get(key)
            if stat is None:
                continue
            finding = self._compare(ctx, key, stat, measured.std)
            if finding is not None:
                findings.append(finding)
        return findings

    def _compare(
        self, ctx: AnalysisContext, key: str, declared: FeatureStats, measured_std: FloatArray
    ) -> Finding | None:
        d_std = float(declared.std)
        m = np.asarray(measured_std, dtype=np.float64)
        m_ref = float(np.median(m[m > 0])) if np.any(m > 0) else 0.0
        if d_std <= 0 or m_ref <= 0:
            return None
        ratio = max(d_std / m_ref, m_ref / d_std)
        if ratio < self._RATIO:
            return None
        return make_finding(
            self,
            severity=Severity.HIGH,
            confidence=1.0,
            title=f"Declared std for '{key}' disagrees with the data by {ratio:.1f}×",
            mechanism=(
                "Stale normalization metadata is baked into the model and mis-scales actions "
                "at inference — a silent, systematic error."
            ),
            fix_text="Recompute stats.json from the current data before training.",
            provenance=dataset_provenance(ctx),
            evidence=Evidence(
                metrics={"declared_std": d_std, "measured_std": m_ref, "ratio": ratio},
                thresholds={"ratio": self._RATIO},
            ),
        )


def _longest_run(mask: BoolArray) -> int:
    """Length of the longest run of True in a boolean mask, counting rows involved."""
    if mask.size == 0 or not mask.any():
        return 0
    best = run = 0
    for v in mask:
        run = run + 1 if v else 0
        best = max(best, run)
    return best + 1 if best else 0  # +1: N identical *transitions* span N+1 rows


class SplitLeakageDetector(Detector):
    """Near-duplicate episodes straddling a declared train/val boundary (docs/04 §A).

    This is the detector most directly aimed at the product's reason for existing: leakage
    inflates the validation score, so the team's own metrics tell them everything is fine
    while the policy has not generalized at all. A false "all-good" signal is the single
    most expensive failure in the loop, and it is invisible without this check.

    Silent unless the *source* declares splits (robomimic ``mask/``). Inventing a split
    would be worse than not checking.
    """

    id = "integrity.split_leakage"
    family = Family.INTEGRITY
    requires = Requirements(min_episodes=4)
    description = "Detects near-duplicate episodes shared across declared train/val splits."

    #: Two episodes are near-duplicates when their trajectory distance is below this
    #: fraction of the typical *within-split* distance. Relative, so it needs no units.
    _DUP_RATIO = 0.15

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        groups: dict[str, list[int]] = {}
        for i, ep in enumerate(ctx.episodes):
            if ep.split:
                groups.setdefault(ep.split, []).append(i)
        if len(groups) < 2:
            return []

        signatures = [_episode_signature(ep) for ep in ctx.episodes]
        width = max((s.size for s in signatures), default=0)
        if width == 0:
            return []
        matrix = np.vstack([_fit_width(s, width) for s in signatures])

        names = sorted(groups)
        baseline = _within_split_scale(matrix, groups, names)
        if baseline <= 0.0:
            return []
        cutoff = self._DUP_RATIO * baseline

        leaks: list[tuple[str, str]] = []
        for a_name, b_name in ((names[i], names[j]) for i in range(len(names)) for j in range(i + 1, len(names))):
            for i in groups[a_name]:
                for j in groups[b_name]:
                    if float(np.linalg.norm(matrix[i] - matrix[j])) < cutoff:
                        leaks.append((ctx.episodes[i].episode_id, ctx.episodes[j].episode_id))
        if not leaks:
            return []

        affected = {eid for pair in leaks for eid in pair}
        return [
            make_finding(
                self,
                severity=Severity.HIGH,
                confidence=0.9,
                title=f"{len(leaks)} near-duplicate episode pair(s) span the train/val split",
                mechanism=(
                    "Episodes that are near-copies of each other sit on both sides of the "
                    "split, so the validation set is partly memorized rather than held out. "
                    "The validation score comes back optimistic and the team ships a policy "
                    "that has not generalized — the false 'all-good' signal is the most "
                    "expensive failure mode there is, because it stops the search for the bug."
                ),
                fix_text=(
                    "Split by recording session, not by episode. Episodes recorded back-to-back "
                    "share lighting, object placement and operator state, so they must land in "
                    "the same split."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "n_pairs": float(len(leaks)),
                        "n_episodes": float(len(affected)),
                        "cutoff": cutoff,
                    },
                    thresholds={"dup_ratio": self._DUP_RATIO},
                    notes="splits: " + ", ".join(f"{n}={len(groups[n])}" for n in names),
                ),
                locus=Locus(episodes=sorted(affected)[:50]),
                blast=blast_over(len(affected), ctx.profile.n_episodes),
                fix_machine={"action": "split_by_session", "pairs": len(leaks)},
            )
        ]


def _episode_signature(episode: Episode) -> FloatArray:
    """A short, length-invariant fingerprint of a trajectory.

    Resampling to a fixed length makes episodes of different durations comparable, which
    matters because a re-recording of the same motion is rarely the same number of steps.
    """
    action = np.asarray(episode.steps.action, dtype=np.float64)
    if action.size == 0:
        return np.zeros(1, dtype=np.float64)
    target = 16
    idx = np.linspace(0, action.shape[0] - 1, target).round().astype(np.int64)
    return action[idx].ravel()


def _fit_width(signature: FloatArray, width: int) -> FloatArray:
    if signature.size == width:
        return signature
    out = np.zeros(width, dtype=np.float64)
    out[: min(width, signature.size)] = signature[:width]
    return out


def _within_split_scale(
    matrix: FloatArray,
    groups: dict[str, list[int]],
    names: list[str],
) -> float:
    """Typical distance between two episodes of the *same* split — the natural yardstick."""
    distances: list[float] = []
    for name in names:
        members = groups[name]
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                distances.append(float(np.linalg.norm(matrix[members[a]] - matrix[members[b]])))
    return float(np.median(distances)) if distances else 0.0
