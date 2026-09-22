"""Candidate generation."""

from __future__ import annotations

from bohrin._plugins import MUTATORS, load_plugin_classes
from bohrin.mutate.base import MutationOperator


def discover() -> list[MutationOperator]:
    """Every registered mutation operator, instantiated."""
    out: list[MutationOperator] = []
    for name, cls in sorted(load_plugin_classes(MUTATORS).items()):
        if issubclass(cls, MutationOperator):
            inst = cls()
            if not inst.id:
                inst.id = name
            out.append(inst)
    return out


__all__ = ["MutationOperator", "discover"]
