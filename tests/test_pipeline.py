"""End-to-end pipeline over the in-memory adapter (docs/06 P1 DoD)."""

from __future__ import annotations

import _synth
import bohrin
from bohrin.ir.schema import Severity
from bohrin.report.tty import TtyRenderer


def test_scan_runs_end_to_end_on_clean_data() -> None:
    path = _synth.register_memory_dataset(_synth.clean_dataset())
    report = bohrin.scan(path)

    assert report.dataset.format == "memory"
    assert report.dataset.n_episodes == 16
    assert report.dataset.action_dim == 6
    # Clean data → no HIGH findings (the zero-false-HIGH bar).
    assert report.max_severity() != Severity.HIGH


def test_scan_surfaces_a_planted_dead_dimension() -> None:
    episodes = _synth.inject_dead_dimension(_synth.clean_dataset(), dim=3)
    path = _synth.register_memory_dataset(episodes)
    report = bohrin.scan(path)

    cluster = report.cluster("stats.dead_dimension")
    assert cluster is not None
    assert cluster.severity is Severity.HIGH
    assert cluster.findings[0].locus.dimensions == [3]


def test_tty_renderer_emits_findings() -> None:
    episodes = _synth.inject_dead_dimension(_synth.clean_dataset(), dim=3)
    path = _synth.register_memory_dataset(episodes)
    report = bohrin.scan(path)
    text = TtyRenderer().render(report)
    assert "by family" in text
    assert "roll" in text  # dim 3 name in the default schema
