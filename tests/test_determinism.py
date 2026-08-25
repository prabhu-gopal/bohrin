"""Determinism: same data → byte-identical report (docs/02 §9, docs/06 P1)."""

from __future__ import annotations

import _synth
import bohrin


def test_two_scans_are_byte_identical() -> None:
    path = _synth.register_memory_dataset(_synth.inject_dead_dimension(_synth.clean_dataset()))
    assert bohrin.scan(path).to_json() == bohrin.scan(path).to_json()


def test_seed_is_threaded_but_findings_are_stable() -> None:
    path = _synth.register_memory_dataset(_synth.inject_dead_dimension(_synth.clean_dataset()))
    assert bohrin.scan(path, seed=0).cluster("stats.dead_dimension") is not None
    assert bohrin.scan(path, seed=7).cluster("stats.dead_dimension") is not None
