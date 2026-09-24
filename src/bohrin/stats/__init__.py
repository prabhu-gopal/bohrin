"""Statistics for evaluations: intervals suited to the sample, detectable differences, aggregation audits."""

from __future__ import annotations

from bohrin.stats.power import PowerReport, analyse, render
from bohrin.stats.results import Row, read_results

__all__ = ["PowerReport", "Row", "analyse", "read_results", "render"]
