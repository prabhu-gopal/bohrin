"""Strict readers for untrusted JSON: a value is exactly the type the published schema says, or it is refused.

JSON read from a file or another tool is untrusted. Python would happily accept ``"false"`` where a
boolean belongs (and treat it as true), ``True`` where an integer belongs, or ``null`` where an
object belongs; each of those is a record the published schema refuses. These helpers refuse them
too, so the code and the schema agree on every record (``tests/test_finding.py`` checks each
field of each format against the schema).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

T = TypeVar("T")

DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def obj(value: Any, where: str, allowed: frozenset[str], required: frozenset[str] = frozenset()) -> Mapping[str, Any]:
    """An object with only ``allowed`` keys and every ``required`` one."""
    if not isinstance(value, dict):
        raise ValueError(f"{where}: expected an object")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{where}: fields not defined by the schema: {unknown}")
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"{where}: missing {missing}")
    return value


def string(value: Any, where: str, *, empty: bool = True, pattern: re.Pattern[str] | None = None) -> str:
    """A string; non-empty unless ``empty``; matching ``pattern`` in full when one is given."""
    if not isinstance(value, str):
        raise ValueError(f"{where}: expected a string")
    if not empty and not value:
        raise ValueError(f"{where}: must not be empty")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ValueError(f"{where}: {value!r} is not in the required form")
    return value


def boolean(value: Any, where: str) -> bool:
    """``true`` or ``false``, never a string or a number that Python would read as one."""
    if not isinstance(value, bool):
        raise ValueError(f"{where}: expected true or false")
    return value


def integer(value: Any, where: str, *, minimum: int | None = None) -> int:
    """An integer (a boolean is not one), at least ``minimum``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where}: expected an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{where}: must be at least {minimum}")
    return value


def number(value: Any, where: str) -> float:
    """A finite number (a boolean is not one). NaN and infinity are not JSON."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{where}: expected a number")
    if not math.isfinite(value):
        raise ValueError(f"{where}: must be finite")
    return float(value)


def array(value: Any, where: str, item: Callable[[Any, str], T], *, min_items: int = 0) -> tuple[T, ...]:
    """A list whose every item passes ``item``, with at least ``min_items`` of them."""
    if not isinstance(value, list):
        raise ValueError(f"{where}: expected a list")
    if len(value) < min_items:
        raise ValueError(f"{where}: needs at least {min_items} items")
    return tuple(item(entry, f"{where}[{index}]") for index, entry in enumerate(value))


def finite(value: float, where: str) -> None:
    """Refuse NaN and infinity in a value built in Python, which ``json`` would write as invalid JSON."""
    if not math.isfinite(value):
        raise ValueError(f"{where}: must be finite")
