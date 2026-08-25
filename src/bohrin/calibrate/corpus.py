"""The conformal calibration corpus — per-embodiment reference scores (docs/06 P4, docs/07 §8).

The `ConformalCalibrator` gives a finite-sample false-positive bound *when it calibrates
against a clean reference set*. Self-calibrating against the dataset's own bulk cannot supply
one — a dataset small or dirty enough has no clean majority to trust, and a rank within the
data under test is not a statement about known-good data (docs/06, deviation 3). This module
is the reference set: non-conformity scores collected from datasets a human has vouched for,
keyed by embodiment and detector, which :mod:`bohrin.calibrate.gate` then calibrates against.

**Keying by embodiment is Mondrian conformal prediction.** Splitting the calibration set by a
taxonomy and calibrating within each stratum is exactly the Mondrian construction, and it is
what buys *group-conditional* validity: the `--fpr` bound holds per embodiment rather than
only on average across a corpus that might be 90 % one robot. `resolve()` is the taxonomy
function, with `"*"` as the fallback category.

**What ships vs what's collected.** The *code* here is complete — load, resolve, accumulate
and save — and `bohrin calibrate` (see :mod:`bohrin.calibrate.collect`) is the tool that
turns known-good datasets into a corpus file. What is *not* shipped is the corpus **data**:
a bundled band would be a claim about robots we have not measured, and a wrong reference
distribution is worse than none because it converts an honest fallback into a false
guarantee. So `CalibrationCorpus.load()` returns an empty corpus when no bundle is present,
every detector keeps self-calibrating exactly as before, and each finding says which gate
produced it. Point `--calibration` at a corpus built from your own known-good data — which
is *better* than a shipped one, since it is conditioned on your embodiment and your rig — and
`--fpr` begins to govern the gate with no detector change.

Corpus file format (JSON), so a corpus can be produced offline and shipped as data:

    {
      "version": "1.0",
      "embodiments": {
        "so101": { "smoothness.jerk_outlier": [0.12, 0.15, ...], ... },
        "*":      { "stats.normalization_outliers": [ ... ] }
      }
    }

``"*"`` is the embodiment-agnostic fallback used when the dataset's embodiment has no entry.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import numpy as np

from bohrin._arrays import FloatArray

CORPUS_VERSION = "1.0"
#: The embodiment key that applies when the dataset's own embodiment is not in the corpus.
WILDCARD = "*"
#: A reference band needs at least this many samples for its p-values to mean anything.
#: Below it, `resolve` returns ``None`` and the detector keeps self-calibrating — better an
#: honest MAD-z gate than a false finite-sample bound from a handful of points.
MIN_REFERENCE = 50
#: The bundled corpus file, looked up as package data so it works from a wheel.
_BUNDLED = "reference.json"


@dataclass(frozen=True, slots=True)
class CalibrationCorpus:
    """Reference non-conformity scores, keyed by ``embodiment → detector_id → scores``."""

    version: str
    by_embodiment: Mapping[str, Mapping[str, FloatArray]]

    @staticmethod
    def empty() -> CalibrationCorpus:
        """A corpus with no references — every ``resolve`` returns ``None``."""
        return CalibrationCorpus(version=CORPUS_VERSION, by_embodiment={})

    @property
    def is_empty(self) -> bool:
        return not self.by_embodiment

    def resolve(self, detector_id: str, embodiment: str | None) -> FloatArray | None:
        """The reference band for ``detector_id`` under ``embodiment``, or ``None``.

        Tries the exact embodiment first, then the ``"*"`` wildcard. Returns ``None`` — so
        the caller falls back to self-calibration — when there is no entry or too few
        samples for a trustworthy bound.
        """
        for key in (embodiment, WILDCARD):
            if key is None:
                continue
            band = self.by_embodiment.get(key, {}).get(detector_id)
            if band is not None and band.size >= MIN_REFERENCE:
                return band
        return None

    @classmethod
    def from_dict(cls, blob: Mapping[str, object]) -> CalibrationCorpus:
        """Parse a corpus from a decoded JSON mapping. Unknown/malformed entries are dropped."""
        version = str(blob.get("version", CORPUS_VERSION))
        raw = blob.get("embodiments", {})
        by_embodiment: dict[str, dict[str, FloatArray]] = {}
        if isinstance(raw, Mapping):
            for embodiment, detectors in raw.items():
                if not isinstance(detectors, Mapping):
                    continue
                bands: dict[str, FloatArray] = {}
                for detector_id, scores in detectors.items():
                    if isinstance(scores, (list, tuple)) and scores:
                        bands[str(detector_id)] = np.asarray(scores, dtype=np.float64).ravel()
                if bands:
                    by_embodiment[str(embodiment)] = bands
        return cls(version=version, by_embodiment=by_embodiment)

    def to_dict(self) -> dict[str, object]:
        """The JSON-ready mapping — the inverse of :meth:`from_dict`.

        Bands are emitted **sorted**, which costs nothing (a reference band is a set of
        exchangeable draws, so order carries no information) and makes a corpus file
        byte-reproducible and diffable across collection runs.
        """
        embodiments: dict[str, dict[str, list[float]]] = {}
        for embodiment in sorted(self.by_embodiment):
            bands = self.by_embodiment[embodiment]
            embodiments[embodiment] = {
                detector_id: [float(v) for v in np.sort(bands[detector_id])] for detector_id in sorted(bands)
            }
        return {"version": self.version, "embodiments": embodiments}

    def save(self, path: str | Path) -> None:
        """Write this corpus as JSON to ``path`` (creating parent directories)."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n", encoding="utf-8")

    def coverage(self) -> dict[str, int]:
        """``"embodiment/detector_id" → band size`` — what a corpus actually covers.

        Surfaced by ``bohrin calibrate`` so a user can see which detectors their corpus
        upgrades and which are still self-calibrating, rather than having to guess.
        """
        return {
            f"{embodiment}/{detector_id}": int(band.size)
            for embodiment, bands in sorted(self.by_embodiment.items())
            for detector_id, band in sorted(bands.items())
        }

    @classmethod
    def load(cls, path: str | Path | None = None) -> CalibrationCorpus:
        """Load the corpus from ``path``, or the bundled package data, or return empty.

        Never raises on a missing or unreadable corpus: absence is the normal state today,
        and a data-quality tool must not fail to scan because an *optional* calibration
        bundle is absent.
        """
        if path is not None:
            p = Path(path)
            if not p.is_file():
                return cls.empty()
            try:
                return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, ValueError):
                return cls.empty()
        try:
            data = resources.files("bohrin.calibrate").joinpath(_BUNDLED)
            if data.is_file():
                return cls.from_dict(json.loads(data.read_text(encoding="utf-8")))
        except (FileNotFoundError, ModuleNotFoundError, json.JSONDecodeError, ValueError):
            pass
        return cls.empty()


class CorpusBuilder:
    """Accumulates reference scores across several known-good datasets into a corpus.

    One builder spans a whole ``bohrin calibrate`` invocation, so bands from several
    datasets of the *same* embodiment pool into one larger reference set — which is the point,
    since :data:`MIN_REFERENCE` samples is the floor for a band to be usable at all and a
    single small dataset rarely clears it on its own.

    Every band also lands under the ``"*"`` wildcard. A user who calibrates on one robot and
    then scans a second, unseen embodiment is better served by a cross-embodiment reference
    band than by nothing — the bound is weaker (it is no longer group-conditional), but the
    alternative is silently reverting to a hand-picked constant.
    """

    def __init__(self) -> None:
        self._bands: dict[str, dict[str, list[float]]] = {}

    def add(self, embodiment: str | None, detector_id: str, scores: FloatArray) -> None:
        """Fold one detector's non-conformity scores for one dataset into the corpus."""
        values = np.asarray(scores, dtype=np.float64).ravel()
        values = values[np.isfinite(values)]
        if values.size == 0:
            return
        keys = {embodiment or WILDCARD, WILDCARD}
        for key in keys:
            self._bands.setdefault(key, {}).setdefault(detector_id, []).extend(float(v) for v in values)

    def build(self) -> CalibrationCorpus:
        """Freeze the accumulated scores into an immutable :class:`CalibrationCorpus`."""
        by_embodiment = {
            embodiment: {detector_id: np.asarray(values, dtype=np.float64) for detector_id, values in bands.items()}
            for embodiment, bands in self._bands.items()
        }
        return CalibrationCorpus(version=CORPUS_VERSION, by_embodiment=by_embodiment)
