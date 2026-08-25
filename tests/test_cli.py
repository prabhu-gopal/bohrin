"""CLI smoke tests (docs/05 §3)."""

from __future__ import annotations

import json
from pathlib import Path

import _synth
from bohrin.cli import main


def _clean_path() -> str:
    return _synth.register_memory_dataset(_synth.clean_dataset())


def _defective_path() -> str:
    return _synth.register_memory_dataset(_synth.inject_dead_dimension(_synth.clean_dataset()))


def test_scan_command_exits_zero() -> None:
    assert main(["scan", _clean_path()]) == 0


def test_scan_writes_json(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    assert main(["scan", _clean_path(), "--json", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["schema_version"] == "1.0"
    assert data["dataset"]["format"] == "memory"


def test_scan_writes_self_contained_html(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    assert main(["scan", _defective_path(), "--html", str(out)]) == 0
    html = out.read_text()
    assert html.startswith("<!doctype html>")
    assert "nothing left this machine" in html
    assert "http://" not in html and "https://" not in html  # self-contained, no external requests


def test_ci_gate_trips_on_high() -> None:
    assert main(["scan", _defective_path(), "--ci"]) == 1  # dead dim is HIGH
    assert main(["scan", _clean_path(), "--ci"]) == 0  # clean → passes


def test_list_and_explain() -> None:
    assert main(["list-detectors"]) == 0
    assert main(["explain", "stats.dead_dimension"]) == 0
    assert main(["explain", "no.such.detector"]) == 1


def test_version() -> None:
    assert main(["version"]) == 0


# ------------------------------------------------------------------ the calibrate command


def test_calibrate_writes_a_corpus(tmp_path: Path) -> None:
    out = tmp_path / "corpus.json"
    paths = [_synth.register_memory_dataset(_synth.smooth_dataset(n_episodes=16)) for _ in range(3)]
    assert main(["calibrate", *paths, "-o", str(out)]) == 0
    blob = json.loads(out.read_text())
    assert blob["version"] == "1.0"
    assert "synth_arm" in blob["embodiments"]  # keyed by embodiment (the Mondrian category)
    assert "*" in blob["embodiments"]  # …and the cross-embodiment fallback


def test_calibrate_refuses_defective_input_and_exits_nonzero(tmp_path: Path) -> None:
    """Collecting from data that reports HIGH would teach the gate that the defect is normal."""
    out = tmp_path / "corpus.json"
    assert main(["calibrate", _defective_path(), "-o", str(out)]) == 2
    assert not out.exists()


def test_calibrate_force_collects_anyway(tmp_path: Path) -> None:
    out = tmp_path / "corpus.json"
    assert main(["calibrate", _defective_path(), "-o", str(out), "--force"]) == 0
    assert out.exists()


def test_scan_accepts_a_calibration_corpus(tmp_path: Path) -> None:
    out = tmp_path / "corpus.json"
    paths = [_synth.register_memory_dataset(_synth.smooth_dataset(n_episodes=16)) for _ in range(3)]
    assert main(["calibrate", *paths, "-o", str(out)]) == 0
    assert main(["scan", _clean_path(), "--calibration", str(out)]) == 0


def test_scan_with_a_missing_corpus_still_succeeds() -> None:
    """A bad --calibration path must degrade to self-calibration, not abort the scan."""
    assert main(["scan", _clean_path(), "--calibration", "/no/such/corpus.json"]) == 0
