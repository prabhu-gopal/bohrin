"""The Canonical Intermediate Representation (docs/03_CANONICAL_IR.md).

Adapters write the IR; detectors read it; nothing else. This is the contract at the
center of the pipeline — frozen in Phase 0.
"""

from __future__ import annotations

from bohrin.ir.episode import (
    Episode,
    LazyArray,
    LazyImage,
    Step,
    StepView,
    TaskLabel,
)
from bohrin.ir.schema import (
    ActionSpace,
    CameraSpec,
    DatasetSchema,
    Family,
    FeatureStats,
    GripperSpec,
    NormScheme,
    PolicyFamily,
    PolicyProfile,
    Provenance,
    SchemaHints,
    Severity,
)

__all__ = [
    "ActionSpace",
    "CameraSpec",
    "DatasetSchema",
    "Episode",
    "Family",
    "FeatureStats",
    "GripperSpec",
    "LazyArray",
    "LazyImage",
    "NormScheme",
    "PolicyFamily",
    "PolicyProfile",
    "Provenance",
    "SchemaHints",
    "Severity",
    "Step",
    "StepView",
    "TaskLabel",
]
