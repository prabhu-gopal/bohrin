"""Systematic agreement between a published JSON Schema and the code that reads the same records.

Hand-picked broken records test the cases someone thought of. This generates every single-point
breakage of a valid record instead: each field replaced by each JSON type it is not, each field
removed, and an unknown field added to each object. The schema and the reader must give the same
verdict on every one.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from typing import Any

from jsonschema import Draft202012Validator

#: One value of each JSON type, plus empty and whitespace-only strings, common ways to be wrong.
WRONG_VALUES: tuple[Any, ...] = (None, "", "   ", "x", 7, 1.5, True, [], {})


def _paths(value: Any, path: tuple[Any, ...] = ()) -> Iterator[tuple[Any, ...]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield (*path, key)
            yield from _paths(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield (*path, index)
            yield from _paths(child, (*path, index))


def _objects(value: Any, path: tuple[Any, ...] = ()) -> Iterator[tuple[Any, ...]]:
    if isinstance(value, dict):
        yield path
        for key, child in value.items():
            yield from _objects(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _objects(child, (*path, index))


def _parent(data: Any, path: tuple[Any, ...]) -> Any:
    for step in path[:-1]:
        data = data[step]
    return data


def breakages(valid: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """``(description, record)`` for every single-point breakage of ``valid``."""
    for path in _paths(valid):
        for wrong in WRONG_VALUES:
            broken = copy.deepcopy(valid)
            _parent(broken, path)[path[-1]] = wrong
            yield f"{'.'.join(map(str, path))} = {wrong!r}", broken
        if isinstance(path[-1], str):
            broken = copy.deepcopy(valid)
            del _parent(broken, path)[path[-1]]
            yield f"{'.'.join(map(str, path))} removed", broken
    for path in _objects(valid):
        broken = copy.deepcopy(valid)
        target = broken
        for step in path:
            target = target[step]
        target["unexpected"] = 1
        yield f"{'.'.join(map(str, path)) or '(top)'} gains an unknown field", broken


def disagreements(
    valid: dict[str, Any], schema: dict[str, Any], accepts: Callable[[dict[str, Any]], bool]
) -> list[str]:
    """Every breakage on which the schema and the reader disagree."""
    validator = Draft202012Validator(schema)
    out = []
    for description, record in breakages(valid):
        by_schema = not list(validator.iter_errors(record))
        by_code = accepts(record)
        if by_schema != by_code:
            schema_says = "accepts" if by_schema else "refuses"
            code_says = "accepts" if by_code else "refuses"
            out.append(f"{description}: schema {schema_says}, code {code_says}")
    return out
