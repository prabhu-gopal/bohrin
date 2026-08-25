"""Remaining STATS checks: degenerate channels and unit-scale mixing (docs/04 §B).

Two cheap, high-signal checks that rely only on the profile — no episodes, no embeddings.

``constant_or_degenerate_channel`` is the *near*-miss sibling of ``stats.dead_dimension``:
that one fires on exactly zero variance, this one on a channel that technically moves but
carries no usable information. Keeping them separate matters because the fixes differ — a
truly dead channel is a mapping bug, a degenerate one is usually a failing sensor.

``unit_scale_inconsistency`` catches the classic degrees-vs-radians mix, which is invisible
in a summary table and quietly ruins optimization conditioning.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np

from bohrin._arrays import FloatArray
from bohrin.detectors._common import blast_over, dataset_provenance, make_finding, sparkline
from bohrin.detectors.base import AnalysisContext, Detector
from bohrin.ir.schema import Family, Severity
from bohrin.profile.dataset_profile import ChannelStats
from bohrin.report.model import Evidence, Finding, Locus

#: Above the dead-dimension floor, but below this fraction of the channel's own median
#: spread, a channel is moving only as much as sensor noise.
_DEGENERATE_RATIO = 0.02
#: A channel whose samples take fewer distinct values than this is effectively a constant
#: with a stuck bit, not a signal.
_MIN_DISTINCT = 3
#: Orders of magnitude between the widest and narrowest channel before we call it a
#: scale problem. 1.5 decades ≈ 30×, comfortably past honest unit differences.
_SCALE_DECADES = 1.5
#: A range near ±π vs near ±180 is the radians/degrees signature.
_RADIAN_MAX = math.pi * 1.2
_DEGREE_MIN = 90.0


def _channel_ranges(stats: ChannelStats) -> FloatArray:
    return np.asarray(stats.max, dtype=np.float64) - np.asarray(stats.min, dtype=np.float64)


class ConstantOrDegenerateChannelDetector(Detector):
    """Flags channels that move, but only as much as noise — a miswired or failing sensor."""

    id = "stats.constant_or_degenerate_channel"
    family = Family.STATS
    description = "Detects near-constant / low-entropy channels that carry no usable signal."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        out: list[Finding] = []
        out.extend(self._scan(ctx, ctx.profile.action, ctx.schema.action_names, "action"))
        if ctx.profile.proprio is not None:
            out.extend(self._scan(ctx, ctx.profile.proprio, ctx.schema.proprio_names, "proprio"))
        return out

    def _scan(
        self,
        ctx: AnalysisContext,
        stats: ChannelStats,
        names: tuple[str, ...] | None,
        channel: str,
    ) -> list[Finding]:
        std = np.asarray(stats.std, dtype=np.float64)
        if stats.dim == 0:
            return []
        # Compare each channel to the *typical* channel of the same signal, so this is
        # unit-free and does not need to know whether we are in metres or radians.
        reference = float(np.median(std[std > 0])) if np.any(std > 0) else 0.0
        if reference <= 0.0:
            return []  # everything is dead; stats.dead_dimension owns that case

        out: list[Finding] = []
        for dim in range(stats.dim):
            if std[dim] <= 0.0:
                continue  # exactly constant → stats.dead_dimension, not this detector
            if std[dim] >= _DEGENERATE_RATIO * reference:
                continue
            distinct = 0
            if stats.sample.size and stats.sample.shape[1] > dim:
                distinct = int(np.unique(np.round(stats.sample[:, dim], 9)).size)
            name = names[dim] if names and dim < len(names) else f"dim{dim}"
            out.append(
                make_finding(
                    self,
                    severity=Severity.MEDIUM if distinct <= _MIN_DISTINCT else Severity.LOW,
                    confidence=0.9,
                    title=f"{channel} '{name}' barely varies — sensor not recording?",
                    mechanism=(
                        "The channel moves far less than every other channel in the same "
                        "vector. It occupies an input dimension while carrying essentially no "
                        "information, which at best wastes capacity and at worst means a sensor "
                        "is disconnected or stuck."
                    ),
                    fix_text=(
                        f"Check the sensor or mapping behind '{name}'. If it is genuinely "
                        "constant for this task, drop it from the vector."
                    ),
                    provenance=dataset_provenance(ctx),
                    evidence=Evidence(
                        metrics={
                            "std": float(std[dim]),
                            "typical_std": reference,
                            "distinct_values": float(distinct),
                        },
                        thresholds={"ratio": _DEGENERATE_RATIO},
                        series=sparkline(stats.sample[:, dim]) if stats.sample.size else [],
                        series_label=f"{channel}[{dim}] '{name}' over sampled steps",
                    ),
                    locus=Locus(dimensions=[dim], dimension_names=[name]),
                    blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes, frac_steps=1.0),
                    fix_machine={"action": "check_sensor", "channel": channel, "dimension": dim},
                )
            )
        return out


class UnitScaleInconsistencyDetector(Detector):
    """Flags channels whose scales differ by orders of magnitude — often degrees vs radians."""

    id = "stats.unit_scale_inconsistency"
    family = Family.STATS
    description = "Detects mixed units / wildly different per-dimension scales in one vector."

    def run(self, ctx: AnalysisContext) -> Iterable[Finding]:
        out: list[Finding] = []
        out.extend(self._scan(ctx, ctx.profile.action, ctx.schema.action_names, "action"))
        if ctx.profile.proprio is not None:
            out.extend(self._scan(ctx, ctx.profile.proprio, ctx.schema.proprio_names, "proprio"))
        return out

    def _scan(
        self,
        ctx: AnalysisContext,
        stats: ChannelStats,
        names: tuple[str, ...] | None,
        channel: str,
    ) -> list[Finding]:
        if stats.dim < 2:
            return []
        ranges = _channel_ranges(stats)
        live = ranges[ranges > 0]
        if live.size < 2:
            return []
        widest, narrowest = float(np.max(live)), float(np.min(live))
        decades = math.log10(widest / narrowest) if narrowest > 0 else 0.0
        if decades < _SCALE_DECADES:
            return []

        wide_dim = int(np.argmax(ranges))
        narrow_dim = int(np.argmin(np.where(ranges > 0, ranges, np.inf)))
        radians_degrees = narrowest <= _RADIAN_MAX and widest >= _DEGREE_MIN
        hint = (
            " The narrow channels span about ±π while the wide ones span about ±180 — "
            "that is the radians-versus-degrees signature."
            if radians_degrees
            else ""
        )
        return [
            make_finding(
                self,
                severity=Severity.MEDIUM,
                confidence=0.95 if radians_degrees else 0.7,
                title=(
                    f"{channel} channels mix scales by {10**decades:.0f}× "
                    + ("— degrees vs radians?" if radians_degrees else "")
                ).strip(),
                mechanism=(
                    "Channels in one vector spanning wildly different magnitudes make the "
                    "optimization ill-conditioned: the loss is dominated by the largest-scale "
                    "dimension, and the small-scale ones are effectively ignored." + hint
                ),
                fix_text=(
                    "Convert every channel to consistent units before training, or normalize "
                    "per dimension so each contributes comparably to the loss."
                ),
                provenance=dataset_provenance(ctx),
                evidence=Evidence(
                    metrics={
                        "widest_range": widest,
                        "narrowest_range": narrowest,
                        "decades": decades,
                    },
                    thresholds={"decades": _SCALE_DECADES},
                    series=sparkline(ranges),
                    series_label=f"{channel} per-dimension range",
                ),
                locus=Locus(
                    dimensions=[narrow_dim, wide_dim],
                    dimension_names=[
                        names[d] if names and d < len(names) else f"dim{d}" for d in (narrow_dim, wide_dim)
                    ],
                ),
                blast=blast_over(ctx.profile.n_episodes, ctx.profile.n_episodes, frac_steps=1.0),
                fix_machine={"action": "normalize_units", "channel": channel},
            )
        ]
