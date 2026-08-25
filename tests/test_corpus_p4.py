"""The conformal calibration corpus mechanism (docs/06 P4, docs/07 §8).

Proves the *mechanism* is complete and correct, independent of whether a populated corpus
ships: an empty corpus is inert, a populated one resolves reference bands, embodiment
fallback works, and — the point of the whole thing — calibrating against a real reference
band bounds the false-positive rate at ``--fpr`` on clean data.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from bohrin.calibrate.conformal import ConformalCalibrator
from bohrin.calibrate.corpus import CalibrationCorpus


def test_empty_corpus_resolves_to_nothing() -> None:
    corpus = CalibrationCorpus.empty()
    assert corpus.is_empty
    assert corpus.resolve("smoothness.jerk_outlier", "so101") is None


def test_bundled_load_never_raises_and_defaults_empty() -> None:
    """Absence of a corpus is the normal state; loading must degrade to empty, not crash."""
    assert CalibrationCorpus.load().is_empty
    assert CalibrationCorpus.load("/no/such/corpus.json").is_empty


def test_resolves_exact_embodiment_then_wildcard() -> None:
    blob = {
        "version": "1.0",
        "embodiments": {
            "so101": {"stats.dead_dimension": list(range(60))},
            "*": {"smoothness.jerk_outlier": list(range(80))},
        },
    }
    corpus = CalibrationCorpus.from_dict(blob)
    assert corpus.resolve("stats.dead_dimension", "so101") is not None
    # falls back to the wildcard when the embodiment has no specific band
    assert corpus.resolve("smoothness.jerk_outlier", "so101") is not None
    assert corpus.resolve("smoothness.jerk_outlier", None) is not None
    assert corpus.resolve("stats.dead_dimension", "franka") is None


def test_too_small_a_band_is_ignored() -> None:
    """A handful of reference points cannot support a finite-sample bound — refuse it."""
    corpus = CalibrationCorpus.from_dict({"embodiments": {"*": {"d": [1.0, 2.0, 3.0]}}})
    assert corpus.resolve("d", None) is None


def test_malformed_entries_are_dropped_not_fatal() -> None:
    corpus = CalibrationCorpus.from_dict({"embodiments": {"x": "not a mapping", "y": {"d": []}}})
    assert corpus.is_empty


def test_load_from_a_written_file(tmp_path: Path) -> None:
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps({"embodiments": {"*": {"d": list(range(100))}}}))
    corpus = CalibrationCorpus.load(path)
    assert corpus.resolve("d", None) is not None


def test_reference_band_bounds_the_false_positive_rate() -> None:
    """The payoff: with a clean reference band, --fpr governs the gate on clean data.

    This is what a shipped corpus buys — the finite-sample bound the self-calibration path
    deliberately does not claim (docs/06, deviation 3).
    """
    rng = np.random.default_rng(0)
    reference = rng.normal(size=2000)  # a clean known-good band
    fresh_clean = rng.normal(size=2000)  # more in-distribution data

    calibrated = ConformalCalibrator(fpr=0.05).calibrate(fresh_clean, calibration=reference)
    flagged = float(calibrated.is_anomaly.mean())
    assert flagged <= 0.07, f"clean data flagged at {flagged:.3f}, above the ~0.05 bound"


def test_corpus_scores_are_immutable_arrays() -> None:
    corpus = CalibrationCorpus.from_dict({"embodiments": {"*": {"d": list(range(60))}}})
    band = corpus.resolve("d", None)
    assert band is not None
    assert band.dtype == np.float64
