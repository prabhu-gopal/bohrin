"""Entry-point plugin discovery (docs/02 §10).

The standard-library ``importlib.metadata`` route (non-provisional since 3.10). Both
built-in adapters/detectors and third-party ones advertise themselves through the same
entry-point groups — there is no privileged path. A plugin whose ``.load()`` raises is
skipped with a warning rather than crashing the whole scan.
"""

from __future__ import annotations

import warnings
from importlib.metadata import entry_points


def load_plugin_classes(group: str) -> dict[str, type]:
    """Load every *class* advertised under ``group``, keyed by entry-point name.

    Entries that fail to import, or that resolve to a non-class, are warned about and
    skipped so one bad plugin can never take down the tool. Callers narrow the result to
    the base they expect (adapter / detector) via ``issubclass``.
    """
    found: dict[str, type] = {}
    for ep in entry_points(group=group):
        try:
            obj = ep.load()
        except Exception as exc:  # a plugin must never crash discovery
            warnings.warn(
                f"bohrin: failed to load plugin {ep.name!r} from {group!r}: {exc}",
                stacklevel=2,
            )
            continue
        if not isinstance(obj, type):
            warnings.warn(
                f"bohrin: plugin {ep.name!r} in {group!r} is not a class; skipping",
                stacklevel=2,
            )
            continue
        found[ep.name] = obj
    return found
