"""Adapter discovery and format detection."""

from __future__ import annotations

from pathlib import Path

from bohrin._plugins import ADAPTERS, load_plugin_classes
from bohrin.adapters.base import Adapter, UnknownFormatError

#: Confidence below which a detection is not trusted.
_MIN_CONFIDENCE = 0.5


def discover() -> list[Adapter]:
    """Every registered adapter, instantiated."""
    out: list[Adapter] = []
    for name, cls in sorted(load_plugin_classes(ADAPTERS).items()):
        if issubclass(cls, Adapter):
            inst = cls()
            if not inst.name:
                inst.name = name
            out.append(inst)
    return out


def detect(path: Path, adapters: list[Adapter] | None = None) -> Adapter:
    """Return the adapter most confident about ``path``.

    Raises :class:`UnknownFormatError` naming what is installed, because "unknown format"
    without that list gives the user nothing to act on.
    """
    candidates = adapters if adapters is not None else discover()
    scored = [(a.detect(path), a) for a in candidates]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    if not scored or scored[0][0] < _MIN_CONFIDENCE:
        installed = ", ".join(sorted(a.name for a in candidates)) or "none"
        raise UnknownFormatError(
            f"no adapter recognised {str(path)!r}. Installed adapters: {installed}. "
            f"If this is a verifiers taskset, install the extra: pip install 'bohrin[verifiers]'"
        )
    return scored[0][1]


__all__ = ["detect", "discover"]
