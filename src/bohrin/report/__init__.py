"""Stage ⑥ — the report model and renderers (docs/02 §6, docs/03 §7)."""

from __future__ import annotations

from bohrin.report.base import Renderer
from bohrin.report.html import HtmlRenderer
from bohrin.report.model import (
    BlastRadius,
    Cluster,
    DatasetInfo,
    Evidence,
    Finding,
    Fix,
    Locus,
    Report,
)
from bohrin.report.tty import TtyRenderer

__all__ = [
    "BlastRadius",
    "Cluster",
    "DatasetInfo",
    "Evidence",
    "Finding",
    "Fix",
    "HtmlRenderer",
    "Locus",
    "Renderer",
    "Report",
    "TtyRenderer",
]
