"""Entry-point plugin discovery.

The standard-library ``importlib.metadata`` route (non-provisional since 3.10). Built-in
and third-party probes, adapters and mutation operators all advertise themselves through
the same entry-point groups — there is no privileged path, and nothing here checks a
licence.

A plugin whose ``.load()`` raises is skipped with a warning rather than crashing the whole
audit. One bad plugin must never take down discovery.
"""

from __future__ import annotations

import warnings
from importlib.metadata import entry_points

PROBES = "bohrin.probes"
ADAPTERS = "bohrin.adapters"
MUTATORS = "bohrin.mutators"


def load_plugin_classes(group: str) -> dict[str, type]:
    """Load every *class* advertised under ``group``, keyed by entry-point name.

    Entries that fail to import, or that resolve to a non-class, are warned about and
    skipped. Callers narrow the result to the base they expect via ``issubclass``.
    """
    found: dict[str, type] = {}
    for ep in entry_points(group=group):
        try:
            obj = ep.load()
        except Exception as exc:  # a plugin must never crash discovery
            warnings.warn(f"bohrin: failed to load plugin {ep.name!r} from {group!r}: {exc}", stacklevel=2)
            continue
        if not isinstance(obj, type):
            warnings.warn(f"bohrin: plugin {ep.name!r} in {group!r} is not a class; skipping", stacklevel=2)
            continue
        found[ep.name] = obj
    return found
