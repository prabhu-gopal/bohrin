"""Detector discovery — the ``bohrin.detectors`` entry-point group (docs/02 §4.1, §10).

Two sources, one registry: classes advertised via entry points (built-in and third-party)
and classes registered programmatically with :func:`register` (the inline-plugin path from
docs/05 §4). ``--only`` / ``--disable`` glob selection is applied here.
"""

from __future__ import annotations

import warnings
from fnmatch import fnmatch

from bohrin._plugins import load_plugin_classes
from bohrin.detectors.base import Detector

ENTRY_POINT_GROUP = "bohrin.detectors"

# Programmatically registered detectors (via @register), keyed by detector id.
_REGISTERED: dict[str, type[Detector]] = {}

#: Detectors excluded from a default scan pending recalibration — not because they are
#: wrong in principle, but because a sweep of 20 real public LeRobot datasets
#: (``scripts/hub_smoke.py``) measured them reporting HIGH on 70% and 60% of curated,
#: widely-used datasets respectively. A HIGH that common is far more likely a threshold
#: problem than a real epidemic, and the report ranks by severity x blast radius — so on
#: the datasets where either fired, it landed in the visible top-6 findings 13 of 16 times,
#: winning the #1 or #2 slot in 6 of those. A first-time user's very first impression of the
#: tool was disproportionately likely to be one of the two things already known to be
#: probably wrong. See ``docs/11_HUB_SMOKE_RESULTS.md``.
#:
#: Nothing here is deleted or degraded: both detectors are fully implemented, benchmarked,
#: and reachable with ``--all``. This set is revisited as each is re-calibrated against real
#: data or a calibration corpus (``bohrin calibrate``) makes ``--fpr`` govern its gate instead.
DEFAULT_EXCLUDED: frozenset[str] = frozenset(
    {
        "smoothness.discontinuity_jump",
        "integrity.declared_mismatch",
    }
)


def register(cls: type[Detector]) -> type[Detector]:
    """Class decorator: register a detector without an entry point (docs/05 §4).

    Used for inline/custom detectors in notebooks and scripts. Built-ins use entry points.
    """
    if not cls.id:
        raise ValueError(f"{cls.__name__} must set a non-empty `id` before registering")
    _REGISTERED[cls.id] = cls
    return cls


def _matches_any(detector_id: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch(detector_id, pat) for pat in patterns)


def discover(
    *,
    only: tuple[str, ...] = (),
    disable: tuple[str, ...] = (),
) -> list[Detector]:
    """Instantiate all known detectors, honoring ``only``/``disable`` globs.

    Entry-point detectors and registered detectors are merged (registered wins on an id
    clash). The result is sorted by id for deterministic ordering (docs/02 §9).
    """
    classes: dict[str, type[Detector]] = {}
    for name, cls in load_plugin_classes(ENTRY_POINT_GROUP).items():
        if not issubclass(cls, Detector):
            warnings.warn(f"bohrin: {name!r} is not a Detector subclass; skipping", stacklevel=2)
            continue
        if cls.id:
            classes[cls.id] = cls
    classes.update(_REGISTERED)

    detectors: list[Detector] = []
    for det_id in sorted(classes):
        if only and not _matches_any(det_id, only):
            continue
        if disable and _matches_any(det_id, disable):
            continue
        detectors.append(classes[det_id]())
    return detectors
