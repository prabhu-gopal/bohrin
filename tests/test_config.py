"""ScanConfig behavior and the bohrin.yaml loader (docs/02 §1.3, §9)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from bohrin.config import ScanConfig, load_yaml


def test_load_yaml_missing_returns_empty(tmp_path: Path) -> None:
    assert load_yaml(tmp_path / "nope.yaml") == {}
    assert load_yaml(tmp_path) == {}  # directory with no bohrin.yaml


def test_load_yaml_reads_schema_map(tmp_path: Path) -> None:
    (tmp_path / "bohrin.yaml").write_text("format: raw_hdf5\ncontrol_hz: 20\n")
    loaded = load_yaml(tmp_path)  # directory → looks for bohrin.yaml inside
    assert loaded["format"] == "raw_hdf5"
    assert loaded["control_hz"] == 20


def test_load_yaml_rejects_non_mapping(tmp_path: Path) -> None:
    (tmp_path / "bohrin.yaml").write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="mapping"):
        load_yaml(tmp_path)


def test_max_episodes_respects_full() -> None:
    triage = ScanConfig(path="toy", sample_episodes=5)
    assert triage.max_episodes() == 5
    full = ScanConfig(path="toy", sample_episodes=5, full=True)
    assert full.max_episodes() is None


def test_rng_is_seeded_and_reproducible() -> None:
    cfg = ScanConfig(path="toy", seed=42)
    a = cfg.rng().integers(0, 1_000_000, size=10)
    b = cfg.rng().integers(0, 1_000_000, size=10)
    np.testing.assert_array_equal(a, b)


def test_with_overrides_is_immutable() -> None:
    cfg = ScanConfig(path="toy")
    changed = cfg.with_overrides(full=True)
    assert cfg.full is False and changed.full is True
