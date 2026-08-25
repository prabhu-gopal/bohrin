"""Small standard-library shims so the package runs on Python 3.10.

A large share of the LeRobot / ROS / CUDA world is still pinned to 3.10-3.11, and a
`requires-python` floor they cannot meet fails at ``pip install`` -- silently, from our
point of view, because the user never files an issue. The floor is therefore 3.10 and
this module carries the (very small) cost of that.

``StrEnum`` (3.11+) and ``typing.Self`` (3.11+) are the only two constructs from later
Python that the rest of the package uses.

The ``StrEnum`` fallback reproduces the two behaviours we actually depend on: members
compare equal to their ``str`` value, and ``str(member)`` yields that value rather than
``"Class.MEMBER"`` (the plain ``str, Enum`` mixin does the latter on 3.10, which would
corrupt every f-string in the report layer). Explicit methods, not assigned-from-``str``
dunders, because mypy types ``str.__format__`` as unbound and rejects the assignment.
"""

from __future__ import annotations

import enum
import sys

if sys.version_info >= (3, 11):
    StrEnum = enum.StrEnum
    from typing import Self as Self
else:  # pragma: no cover - exercised by the 3.10 CI leg
    from typing_extensions import Self as Self

    class StrEnum(str, enum.Enum):
        """Backport of :class:`enum.StrEnum` (Python 3.11+)."""

        def __str__(self) -> str:
            return str.__str__(self)

        def __format__(self, format_spec: str) -> str:
            return str.__format__(self, format_spec)


__all__ = ["Self", "StrEnum"]
