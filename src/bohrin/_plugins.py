"""Entry-point plugin discovery.

The standard-library ``importlib.metadata`` route (non-provisional since 3.10), as the Python
Packaging User Guide recommends. Built-in and third-party plugins advertise themselves through the
same entry-point groups; there is no privileged path, and nothing here checks a licence.

Three rules keep one plugin from harming the rest:

* **A plugin that fails to load is skipped**, with a warning. It never crashes discovery.
* **A name belongs to its first owner.** When two installed packages register the same name in a
  group, the one from this package (``bohrin``) keeps it, and otherwise the first by package name.
  The other is skipped with a warning. So no installed package can silently replace a built-in,
  such as a command that reports what a change did to the tests.
* **A plugin built for another seam version is skipped.** A plugin class may declare
  ``plugin_api``; when it differs from :data:`PLUGIN_API`, it was written against a seam this
  release does not provide.
"""

from __future__ import annotations

import warnings
from importlib.metadata import EntryPoint, entry_points

#: The version of the seam in ``bohrin.api``. It changes only when the seam breaks: a name removed
#: or a signature changed incompatibly. Adding a name keeps it.
PLUGIN_API = 1

#: This package's own distribution name.
_OWN = "bohrin"

MUTATORS = "bohrin.mutators"
RELATIONS = "bohrin.relations"
COMMANDS = "bohrin.commands"
ADAPTERS = "bohrin.adapters"
PROBES = "bohrin.probes"
RENDERERS = "bohrin.renderers"
#: Every entry-point group Bohrin reads. The names are public API.
GROUPS = (MUTATORS, RELATIONS, COMMANDS, ADAPTERS, PROBES, RENDERERS)


def _owner(entry: EntryPoint) -> str:
    return entry.dist.name if entry.dist is not None else ""


def _ordered(group: str) -> list[EntryPoint]:
    """This package's entries first, then every other package's in package-name order."""
    return sorted(entry_points(group=group), key=lambda e: (_owner(e) != _OWN, _owner(e), e.name))


def load_plugin_classes(group: str) -> dict[str, type]:
    """Load every *class* advertised under ``group``, keyed by entry-point name.

    Entries that fail to import, that resolve to a non-class, that declare another
    ``plugin_api``, or whose name is already taken, are warned about and skipped. Callers narrow
    the result to the base they expect via ``issubclass``.
    """
    found: dict[str, type] = {}
    owners: dict[str, str] = {}
    for ep in _ordered(group):
        if ep.name in found:
            warnings.warn(
                f"bohrin: {_owner(ep) or 'a package'} registers {ep.name!r} in {group!r}, which "
                f"{owners[ep.name]} already provides; keeping {owners[ep.name]}'s",
                stacklevel=2,
            )
            continue
        try:
            obj = ep.load()
        except Exception as exc:  # a plugin must never crash discovery
            warnings.warn(f"bohrin: failed to load plugin {ep.name!r} from {group!r}: {exc}", stacklevel=2)
            continue
        if not isinstance(obj, type):
            warnings.warn(f"bohrin: plugin {ep.name!r} in {group!r} is not a class; skipping", stacklevel=2)
            continue
        declared = getattr(obj, "plugin_api", PLUGIN_API)
        if declared != PLUGIN_API:
            warnings.warn(
                f"bohrin: plugin {ep.name!r} in {group!r} was written for plugin API {declared!r}; "
                f"this release provides {PLUGIN_API}. Skipping it; install a matching version.",
                stacklevel=2,
            )
            continue
        found[ep.name] = obj
        owners[ep.name] = _owner(ep) or "a package"
    return found
