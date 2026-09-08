"""Resolving an installed distribution name from a package directory.

Both `verifiers` adapters need the same fact about a path — the distribution name declared
in its ``pyproject.toml`` — because upstream resolves an environment id to an *installed*
module in both APIs. It lives here rather than in either adapter so that neither imports
the other's privates.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

#: The file that names a Python distribution on disk.
PYPROJECT = "pyproject.toml"


def distribution_name(path: Path) -> str | None:
    """The distribution name declared under ``path``, or None.

    Looks at ``path`` itself and then one level down, because an environment is commonly
    published as a directory holding the package directory alongside its ``pyproject.toml``.
    Returns None rather than guessing a name from the directory: a wrong id produces a
    confusing "not installed" error for a package that is installed under another name.
    """
    candidates = (path / PYPROJECT, *(p / PYPROJECT for p in sorted(path.glob("*")) if p.is_dir()))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            meta = tomllib.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        name = meta.get("project", {}).get("name")
        if isinstance(name, str) and name:
            return name
    return None


__all__ = ["PYPROJECT", "distribution_name"]
