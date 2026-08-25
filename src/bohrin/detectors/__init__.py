"""Stage ④ — the detector battery (docs/02 §4, docs/04_DETECTORS.md)."""

from __future__ import annotations

from bohrin.detectors.base import AnalysisContext, Detector, Requirements
from bohrin.detectors.registry import discover, register

__all__ = ["AnalysisContext", "Detector", "Requirements", "discover", "register"]
