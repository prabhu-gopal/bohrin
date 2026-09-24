"""Canonical JSON, as RFC 8785 (the JSON Canonicalization Scheme) defines it, for the values IDs are made of.

A finding's ID is a hash of JSON, so the JSON must be the same bytes for anyone who computes it,
in any language. RFC 8785 fixes those bytes: no whitespace, strings written as UTF-8 with only the
required escapes, object keys sorted by their UTF-16 code units, output encoded as UTF-8.

The values hashed here are strings, lists, objects, booleans, null and integers. Floating-point
numbers are refused rather than approximated: RFC 8785 serialises them the ECMAScript way, which
Python's ``repr`` does not always match, and no ID input needs one.
"""

from __future__ import annotations

import json
from typing import Any

#: Beyond this, an integer cannot be represented exactly by the IEEE 754 doubles RFC 8785 assumes.
_SAFE_INTEGER = 2**53 - 1


def _sorted(value: Any) -> Any:
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise TypeError(f"object keys must be strings, not {type(key).__name__}")
        return {key: _sorted(value[key]) for key in sorted(value, key=lambda k: k.encode("utf-16-be"))}
    if isinstance(value, list | tuple):
        return [_sorted(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        if abs(value) > _SAFE_INTEGER:
            raise ValueError(f"integer {value} is too large for canonical JSON")
        return value
    raise TypeError(f"canonical JSON does not take {type(value).__name__} values")


def canonical_json(value: Any) -> bytes:
    """The RFC 8785 serialisation of ``value``, as UTF-8 bytes.

    Raises ``TypeError`` for a value it does not take (a float, a non-string key) and
    ``UnicodeEncodeError`` for text that is not valid Unicode (a lone surrogate), which RFC 8785
    requires an implementation to refuse.
    """
    text = json.dumps(_sorted(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return text.encode("utf-8")


__all__ = ["canonical_json"]
