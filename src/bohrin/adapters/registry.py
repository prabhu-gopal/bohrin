"""Adapter discovery + autodetection — the ``bohrin.adapters`` group (docs/02 §1.2, §10).

``bohrin scan <path>`` runs every registered adapter's cheap ``detect(path)`` and picks
the highest confidence. A forced ``--format`` bypasses detection.
"""

from __future__ import annotations

import warnings
from pathlib import Path

from bohrin._plugins import load_plugin_classes
from bohrin.adapters.base import Adapter

ENTRY_POINT_GROUP = "bohrin.adapters"

# Programmatically registered adapters (via @register_adapter), keyed by name.
_REGISTERED: dict[str, type[Adapter]] = {}


def register_adapter(cls: type[Adapter]) -> type[Adapter]:
    """Class decorator: register an adapter without an entry point."""
    if not cls.name:
        raise ValueError(f"{cls.__name__} must set a non-empty `name` before registering")
    _REGISTERED[cls.name] = cls
    return cls


def discover() -> list[Adapter]:
    """Instantiate all known adapters (entry-point + registered), sorted by name."""
    classes: dict[str, type[Adapter]] = {}
    for name, cls in load_plugin_classes(ENTRY_POINT_GROUP).items():
        if not issubclass(cls, Adapter):
            warnings.warn(f"bohrin: {name!r} is not an Adapter subclass; skipping", stacklevel=2)
            continue
        if cls.name:
            classes[cls.name] = cls
    classes.update(_REGISTERED)
    return [classes[name]() for name in sorted(classes)]


class UnknownFormatError(RuntimeError):
    """Raised when no adapter recognizes a path and none was forced via ``--format``."""


def select_adapter(path: str | Path, *, forced_format: str | None = None) -> Adapter:
    """Pick the adapter for ``path`` — forced format if given, else best ``detect`` score."""
    adapters = discover()
    if forced_format is not None:
        for a in adapters:
            if a.name == forced_format:
                return a
        known = ", ".join(sorted(a.name for a in adapters)) or "none"
        raise UnknownFormatError(f"unknown --format {forced_format!r}; installed: {known}")

    p = Path(path)
    best: Adapter | None = None
    best_score = 0.0
    for a in adapters:
        score = a.detect(p)
        if score > best_score:
            best, best_score = a, score
    if best is None or best_score <= 0.0:
        # Only *now* do we care whether the path exists: an adapter may legitimately serve a
        # non-filesystem target (an in-memory or remote handle), so a missing file is a
        # better error message, never a gate.
        if not p.exists():
            raise FileNotFoundError(
                f"no such path: {str(p)!r}. If you meant a dataset on the Hugging Face Hub, pass "
                f"it as owner/name (for example: bohrin scan lerobot/pusht)."
            )
        raise UnknownFormatError(_undetected_message(p, adapters))
    return best


def _undetected_message(p: Path, adapters: list[Adapter]) -> str:
    """Explain *why* nothing matched, and name the next step — never just "unknown format".

    The three cases a user actually hits are distinguishable from the filesystem alone, and
    each has a different fix, so we branch rather than emitting one generic sentence.
    """
    known = ", ".join(sorted(a.name for a in adapters)) or "none"
    if p.is_dir() and not (p / "meta" / "info.json").is_file():
        contents = sorted(c.name for c in p.iterdir())[:6]
        listing = ", ".join(contents) if contents else "(empty)"
        return (
            f"not a LeRobot dataset: no meta/info.json found in {str(p)!r} (contains: {listing}). "
            f"bohrin also reads robomimic/raw HDF5, Zarr replay buffers, RLDS and NumPy directories "
            f"— force one with --format <name>. Installed adapters: {known}."
        )
    if p.is_file():
        return (
            f"{str(p)!r} is a single file, and no adapter recognized it. HDF5 (.hdf5/.h5) needs "
            f"`pip install bohrin[hdf5]`. Point bohrin at the dataset *directory* if this file is "
            f"part of one. Installed adapters: {known}."
        )
    return f"could not detect the format of {str(p)!r}. Try --format. Installed adapters: {known}."
