"""Shared analysis primitives for the detector battery (docs/07).

Format-agnostic math over the Canonical IR: trajectory shape, kernel two-sample testing,
nearest-neighbour structure, and episode embeddings. Detectors compose these rather than
re-implementing statistics, so the methods stay consistent and testable in one place.
"""

from __future__ import annotations

from bohrin.analysis.embeddings import (
    initial_states,
    shape_embedding,
    stack,
    standardize,
    summary_embedding,
    trajectory,
)
from bohrin.analysis.neighbors import effective_diversity, knn, non_iid_pvalue
from bohrin.analysis.shapes import (
    dtw_distance,
    is_multimodal,
    path_length,
    resample,
    top_variance_ratio,
)
from bohrin.analysis.twosample import mmd2_unbiased, mmd_permutation_test

__all__ = [
    "dtw_distance",
    "effective_diversity",
    "initial_states",
    "is_multimodal",
    "knn",
    "mmd2_unbiased",
    "mmd_permutation_test",
    "non_iid_pvalue",
    "path_length",
    "resample",
    "shape_embedding",
    "stack",
    "standardize",
    "summary_embedding",
    "top_variance_ratio",
    "trajectory",
]
