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

#: Detectors excluded from a default scan pending recalibration. None of them is wrong in
#: principle; each was *measured* firing too often on curated, widely-used public data to
#: carry information, and gating beats deleting. Nothing here is removed or degraded: every
#: one is fully implemented, benchmarked, and reachable with ``--all``.
#:
#: ``smoothness.discontinuity_jump`` and ``integrity.declared_mismatch`` were excluded first,
#: after a sweep of 20 real public LeRobot datasets measured them reporting HIGH on 70% and
#: 60% of the corpus. Because the report ranks by severity x blast radius, on the datasets
#: where either fired it landed in the visible top findings 13 of 16 times, taking the #1 or
#: #2 slot in 6 of those: a first-time user's very first impression of bohrin was
#: disproportionately likely to be one of the two things already known to be probably wrong.
#:
#: ``dynamics.inverse_residual`` joined them after the 2026-08-26 benchmark
#: (``benchmarks/2026-08-26-lerobot-20-v0.1.0/``) measured it on the same 20 datasets:
#:
#: * fires on **100%** of them (20/20) and reports HIGH on 50% (10/20);
#: * reaches the visible top-5 on 60% of them, more often than either detector above;
#: * excluding it drops the corpus from 23 HIGH findings to 13, and the number of datasets
#:   carrying at least one HIGH from 17/20 to 11/20.
#:
#: Its HIGH rate is *lower* than the two above; the 100% fire rate is what decides it. A
#: detector that fires on every curated public dataset cannot discriminate, whatever severity
#: it attaches. One explanation was tested and rejected: the ridge solve behind it was
#: genuinely ill-conditioned, that is fixed, and the fire and HIGH rates did not move. The
#: two surviving explanations, 5 Hz control rate and RLDS conversion provenance, are perfectly
#: confounded in that corpus, so it cannot be diagnosed there. Recalibration needs a corpus of
#: natively-recorded community datasets.
#:
#: Next candidate, deliberately **not** excluded yet: ``dynamics.forward_residual`` fires on
#: 90% and reaches the top-5 on 75%, the highest visibility of any detector, but never reports
#: HIGH, so it does not break a ``--fail-on HIGH`` gate. Excluding two undiagnosed detectors at
#: once would be over-correction; this set is evidence-gated, not a place to put detectors we
#: are merely unsure of.
#:
#: This set shrinks as each detector is recalibrated against real data, or as a calibration
#: corpus (``bohrin calibrate``) makes ``--fpr`` govern its gate instead.
DEFAULT_EXCLUDED: frozenset[str] = frozenset(
    {
        "smoothness.discontinuity_jump",
        "integrity.declared_mismatch",
        "dynamics.inverse_residual",
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
