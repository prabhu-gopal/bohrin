"""Family B — STATS: are the channels sane and informative? (docs/04 §B).

Operate on the ``DatasetProfile`` (online moments, reservoir quantiles, zero-fraction) —
essentially free after Stage ③. ``stats.dead_dimension`` is the canonical "one part of the
arm never moves" finding.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from bohrin.analysis import embeddings
from bohrin.analysis.twosample import mmd_permutation_test
from bohrin.detectors._common import blast_over, dataset_provenance, make_finding, sparkline
from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.ir.schema import Family, Severity
from bohrin.profile.dataset_profile import ChannelStats
from bohrin.report.model import Evidence, Finding, Locus

_STD_TOL = 1e-9


def _names(names: tuple[str, ...] | None, dim: int) -> str:
    if names is not None and dim < len(names):
        return names[dim]
    return f"dim{dim}"


class DeadDimensionDetector(Detector):
    """Flags action/proprio dimensions with (near) zero variance — a channel never exercised."""

    id = "stats.dead_dimension"
    family = Family.STATS
    description = (
        "Flags action/proprio dimensions with zero variance across the dataset. A joint no "
        "demonstration ever moves cannot be learned — usually a teleop mapping bug."
    )

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        findings: list[Finding] = []
        findings.extend(self._scan(ctx, ctx.profile.action, ctx.schema.action_names, "action"))
        if ctx.profile.proprio is not None:
            findings.extend(self._scan(ctx, ctx.profile.proprio, ctx.schema.proprio_names, "proprio"))
        return findings

    def _scan(
        self,
        ctx: AnalysisContext,
        stats: ChannelStats,
        names: tuple[str, ...] | None,
        channel: str,
    ) -> list[Finding]:
        out: list[Finding] = []
        for dim in range(stats.dim):
            if stats.std[dim] > _STD_TOL:
                continue
            name = _names(names, dim)
            out.append(
                make_finding(
                    self,
                    severity=Severity.HIGH,
                    confidence=1.0,
                    title=f"{channel} dim {dim} ('{name}') never moves in any episode",
                    mechanism=(
                        "A channel with zero variance carries no signal: the policy has no "
                        "example of how to control it, so it can never learn to. This is "
                        "almost always a teleoperation mapping bug."
                    ),
                    fix_text=(
                        f"Verify the teleop mapping records '{name}'. If the joint is truly "
                        "unused, drop it from the vector so the policy isn't asked to predict "
                        "a constant."
                    ),
                    provenance=dataset_provenance(ctx),
                    evidence=Evidence(
                        metrics={"std": float(stats.std[dim]), "mean": float(stats.mean[dim])},
                        thresholds={"std_tol": _STD_TOL},
                        # The flat line is the proof: a reader sees "dead" before reading "std=0".
                        series=sparkline(stats.sample[:, dim]) if stats.sample.size else [],
                        series_label=f"{channel}[{dim}] '{name}' over sampled steps",
                    ),
                    locus=Locus(dimensions=[dim], dimension_names=[name]),
                    blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes, frac_steps=1.0),
                    fix_machine={
                        "action": "drop_or_fix_dimension",
                        "channel": channel,
                        "dimension": dim,
                    },
                )
            )
        return out


class SaturationClippingDetector(Detector):
    """Flags action dims with a mass of samples piled at the exact min or max — clipped."""

    id = "stats.saturation_clipping"
    family = Family.STATS
    description = "Detects actions piled at a control/normalization limit (clipping), which loses gradient signal."

    _FRAC = 0.05  # ≥ 5% of samples exactly at a boundary is a saturation spike

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        stats = ctx.profile.action
        sample = stats.sample
        if sample.shape[0] == 0:
            return []
        findings: list[Finding] = []
        for dim in range(stats.dim):
            col = sample[:, dim]
            span = float(stats.max[dim] - stats.min[dim])
            if span <= _STD_TOL:
                continue  # constant dim → handled by dead_dimension
            at_max = float(np.mean(np.isclose(col, stats.max[dim], atol=span * 1e-4)))
            at_min = float(np.mean(np.isclose(col, stats.min[dim], atol=span * 1e-4)))
            frac = max(at_max, at_min)
            if frac < self._FRAC:
                continue
            name = _names(ctx.schema.action_names, dim)
            boundary = "max" if at_max >= at_min else "min"
            findings.append(
                make_finding(
                    self,
                    severity=Severity.MEDIUM,
                    confidence=min(1.0, frac / self._FRAC * 0.5 + 0.5),
                    title=f"{frac * 100:.0f}% of action '{name}' sits exactly at the {boundary}",
                    mechanism=(
                        "Actions clipped at the control or normalization limit lose gradient "
                        "signal and teach a bang-bang policy; for a model that does not clamp "
                        "outputs (π0), out-of-range targets are worse still."
                    ),
                    fix_text="Check the action/normalization range; widen it or verify the controller isn't clipping.",
                    provenance=dataset_provenance(ctx),
                    evidence=Evidence(metrics={"frac_at_boundary": frac}, thresholds={"frac": self._FRAC}),
                    locus=Locus(dimensions=[dim], dimension_names=[name]),
                    blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes, frac_steps=frac),
                )
            )
        return findings


class NormalizationOutliersDetector(Detector):
    """Flags heavy tails beyond q01/q99 that will dominate mean/std normalization (docs/04 §B)."""

    id = "stats.normalization_outliers"
    family = Family.STATS
    description = "Detects extreme outliers that distort q01/q99 normalization anchors for VLA models."

    _FACTOR = 10.0  # tail extends ≥ 10× the inter-quantile range beyond q99/q01

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        stats = ctx.profile.action
        findings: list[Finding] = []
        for dim in range(stats.dim):
            iqr = float(stats.q99[dim] - stats.q01[dim])
            if iqr <= _STD_TOL:
                continue
            over = float(stats.max[dim] - stats.q99[dim]) / iqr
            under = float(stats.q01[dim] - stats.min[dim]) / iqr
            excess = max(over, under)
            if excess < self._FACTOR:
                continue
            name = _names(ctx.schema.action_names, dim)
            findings.append(
                make_finding(
                    self,
                    severity=Severity.MEDIUM,
                    confidence=1.0,
                    title=f"Action '{name}' has outliers ~{excess:.0f}× beyond its q99 range",
                    mechanism=(
                        "A few wild samples set the normalization scale, squashing the useful "
                        "range of every other sample toward zero — a classic VLA data pitfall."
                    ),
                    fix_text="Clip or remove the extreme outliers, or use quantile (q01/q99) normalization.",
                    provenance=dataset_provenance(ctx),
                    evidence=Evidence(
                        metrics={"excess_over_iqr": excess, "iqr": iqr},
                        thresholds={"factor": self._FACTOR},
                    ),
                    locus=Locus(dimensions=[dim], dimension_names=[name]),
                    blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes),
                )
            )
        return findings


class DistributionDriftDetector(Detector):
    """Flags a distribution shift *inside* the training set, via an MMD two-sample test.

    Compares the first half of the collection against the second half. A significant kernel
    MMD means something changed midway — a recalibration, a swapped tool, a new operator —
    which is a covariate shift the model sees as inconsistent dynamics.
    """

    id = "stats.distribution_drift"
    family = Family.STATS
    requires = Requirements(min_episodes=10)
    description = "Detects a mid-collection distribution shift (recalibration, operator change) via a kernel MMD test."

    _P = 0.01

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        episodes = ctx.episodes
        if len(episodes) < self.requires.min_episodes:
            return []
        matrix = embeddings.standardize(embeddings.stack(episodes))
        if matrix.shape[0] < 10:
            return []
        half = matrix.shape[0] // 2
        mmd2, p_value = mmd_permutation_test(matrix[:half], matrix[half:], rng=ctx.rng)
        if p_value >= self._P:
            return []
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=float(1.0 - p_value),
                title="The dataset's distribution shifts partway through collection",
                mechanism=(
                    "The first and second halves of the collection come from measurably "
                    "different distributions (kernel MMD two-sample test). That is a covariate "
                    "shift *inside* the training set — the model sees inconsistent dynamics for "
                    "what should be the same task."
                ),
                fix_text=(
                    "Check for a recalibration, tool change, or operator change midway; consider "
                    "treating the segments as separate datasets."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(metrics={"mmd_squared": mmd2, "p_value": p_value}, thresholds={"p_value": self._P}),
                blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes),
            )
        ]
