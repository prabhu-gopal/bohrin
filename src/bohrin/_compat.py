"""Small standard-library shims so the package runs on Python 3.10.

A large share of the LeRobot / ROS / CUDA world is still pinned to 3.10-3.11, and a
`requires-python` floor they cannot meet fails at ``pip install`` -- silently, from our
point of view, because the user never files an issue. The floor is therefore 3.10 and
this module carries the (very small) cost of that.

``StrEnum`` is the only 3.11+ construct we use. The fallback reproduces the two
behaviours we actually depend on: members compare equal to their ``str`` value, and
``str(member)`` yields that value rather than ``"Class.MEMBER"`` (the plain
``str, Enum`` mixin does the latter on 3.10, which would corrupt every f-string in the
report layer).
"""

from __future__ import annotations

import enum
import sys

if sys.version_info >= (3, 11):
    StrEnum = enum.StrEnum
else:  # pragma: no cover - exercised by the 3.10 CI leg

    class StrEnum(str, enum.Enum):  # type: ignore[no-redef]
        """Backport of :class:`enum.StrEnum` (Python 3.11+)."""

        __str__ = str.__str__
        __format__ = str.__format__


__all__ = ["StrEnum"]
