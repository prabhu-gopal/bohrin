"""``ScanConfig`` and the ``bohrin.yaml`` loader (docs/02 §1.3, §8).

``ScanConfig`` is the single, immutable bundle of run options threaded through the whole
pipeline. It also owns the **seeded RNG** that makes every run deterministic (docs/02 §9):
sampling, reservoir selection, and any stochastic detector all draw from a generator
derived from ``seed``, so two scans of the same data are byte-identical.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from bohrin.profile.episode_reservoir import DEFAULT_MEMORY_BUDGET_MB

# The default false-positive-rate bound for conformal calibration (docs/07 §4). Wired as
# a contract in P0; the calibration layer that consumes it lands in P1.
DEFAULT_FPR = 0.01

#: Default triage cap: episodes scanned when neither ``--full`` nor ``--sample-episodes`` is
#: given (docs/05 §3 "triage-by-default"). Large enough for the coverage/redundancy families
#: to be statistically meaningful, small enough that a first run on a huge dataset stays fast.
#: The selection is seeded, so the triage is reproducible; ``--full`` removes the cap.
DEFAULT_TRIAGE_EPISODES = 300


#: The per-dataset config file name, resolved relative to the dataset path.
_CONFIG_NAME = "bohrin.yaml"


@dataclass(frozen=True, slots=True)
class ScanConfig:
    """Immutable run options for a single scan."""

    path: str
    #: What the user actually asked for, when that differs from ``path`` — currently only a
    #: Hugging Face repo id, whose ``path`` is an opaque local snapshot directory. The report
    #: shows this, because "lerobot/pusht" is the dataset's identity and the cache path is an
    #: implementation detail nobody can act on.
    source: str | None = None
    format: str | None = None
    policy: str | None = None
    target: str | None = None
    full: bool = False
    sample_episodes: int | None = None
    no_vision: bool = False
    only: tuple[str, ...] = ()
    disable: tuple[str, ...] = ()
    seed: int = 0
    fpr: float = DEFAULT_FPR
    lang: str = "en"
    #: Visual encoder for vision-aware coverage. "tiled" is offline and dependency-free;
    #: "dinov2" needs bohrin[vision] and downloads weights, so it is never chosen implicitly.
    encoder: str = "tiled"
    #: RAM budget (MiB) for the raw episodes held for trajectory-level detectors. The working
    #: set is a *uniform sample* under this budget, so exceeding it costs statistical power,
    #: never correctness (docs/02 §7).
    max_episode_memory_mb: int = DEFAULT_MEMORY_BUDGET_MB
    #: Path to a calibration corpus of reference scores from known-good data, built by
    #: ``bohrin calibrate``. When a band covers a detector, ``fpr`` governs its gate via
    #: conformal FDR; otherwise that detector self-calibrates (docs/07 §4.2).
    calibration: str | None = None
    #: Declared schema map from ``bohrin.yaml`` (docs/02 §1.3), if one was loaded.
    schema_map: Mapping[str, Any] = field(default_factory=dict)

    def display_uri(self) -> str:
        """How this dataset should be named in a report and in copy-pasteable next steps."""
        return self.source or self.path

    def rng(self) -> np.random.Generator:
        """A fresh generator seeded from ``seed`` — the root of all run randomness."""
        return np.random.default_rng(self.seed)

    def max_episodes(self) -> int | None:
        """Episode cap for the scan (docs/05 §3).

        ``--full`` removes the cap (scan everything); an explicit ``--sample-episodes N``
        uses ``N``; otherwise the default triage cap keeps a first run fast. Returning a cap
        here is what makes "triage-by-default" real rather than a docs claim.
        """
        if self.full:
            return None
        return self.sample_episodes if self.sample_episodes is not None else DEFAULT_TRIAGE_EPISODES

    def with_overrides(self, **changes: Any) -> ScanConfig:
        """Return a copy with fields replaced (config stays immutable)."""
        return replace(self, **changes)


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a ``bohrin.yaml`` schema-map file into a plain dict (empty if missing).

    ``path`` is the *dataset* path, which may be a directory (look inside it) or a single
    file such as an HDF5 archive (look for a sibling ``bohrin.yaml``). It is never itself
    parsed as YAML — feeding a binary dataset to the YAML loader would fail with an opaque
    decode error rather than the "no config, use defaults" this function means.
    """
    p = Path(path)
    if p.name != _CONFIG_NAME:
        p = (p if p.is_dir() else p.parent) / _CONFIG_NAME
    if not p.is_file():
        return {}
    loaded: object = yaml.safe_load(p.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        kind = type(loaded).__name__
        raise ValueError(f"{p}: expected a YAML mapping at the top level, got {kind}")
    return dict(loaded)
