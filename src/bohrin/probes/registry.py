"""Probe discovery."""

from __future__ import annotations

from bohrin._plugins import PROBES, load_plugin_classes
from bohrin.probes.base import Probe

#: Probe ids that exist, are implemented and tested, but are held back from a default
#: audit pending recalibration. Reachable with --all.
#:
#: This is not a place to hide a probe nobody likes. An entry here needs measured evidence
#: in its justification, in the commit message and in this docstring — the precedent being
#: that the previous codebase only ever excluded detectors it had measured firing on 60-70%
#: of a real public corpus.
DEFAULT_EXCLUDED: frozenset[str] = frozenset()


def discover(*, include_excluded: bool = False) -> list[Probe]:
    """Every registered probe, instantiated, sorted by id."""
    out: list[Probe] = []
    for name, cls in sorted(load_plugin_classes(PROBES).items()):
        if not issubclass(cls, Probe):
            continue
        if not include_excluded and name in DEFAULT_EXCLUDED:
            continue
        inst = cls()
        if not inst.id:
            inst.id = name
        out.append(inst)
    return out


def get(probe_id: str) -> Probe | None:
    """One probe by id, including those excluded by default."""
    for probe in discover(include_excluded=True):
        if probe.id == probe_id:
            return probe
    return None


__all__ = ["DEFAULT_EXCLUDED", "discover", "get"]
