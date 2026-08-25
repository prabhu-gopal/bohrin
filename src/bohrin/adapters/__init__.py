"""Stage ① — the adapter layer (docs/02 §1, docs/01_DATA_LANDSCAPE.md)."""

from __future__ import annotations

from bohrin.adapters.base import Adapter, DatasetHandle, Sampler
from bohrin.adapters.registry import (
    UnknownFormatError,
    discover,
    register_adapter,
    select_adapter,
)

__all__ = [
    "Adapter",
    "DatasetHandle",
    "Sampler",
    "UnknownFormatError",
    "discover",
    "register_adapter",
    "select_adapter",
]
