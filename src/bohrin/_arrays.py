"""Shared numpy typing aliases used across the IR and detectors.

Keeping these in one place lets ``mypy --strict`` see precise array element types instead
of a bare ``np.ndarray`` (which is generic and would leak ``Any``).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

# A 1-D or 2-D array of float64 (the canonical dtype for actions/proprio after ingest).
FloatArray = npt.NDArray[np.float64]

# Integer arrays (episode indices, counts).
IntArray = npt.NDArray[np.int64]

# Boolean masks (anomaly flags).
BoolArray = npt.NDArray[np.bool_]

# An array of *unknown* dtype — only for the adapter boundary, where a source file may hold
# uint8 pixels, int64 indices or float32 signals and the adapter's job is to coerce them.
# Nothing past Stage ② should use this: the IR is float64 by contract.
AnyArray = npt.NDArray[Any]
