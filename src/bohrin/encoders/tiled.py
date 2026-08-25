"""The zero-dependency default visual encoder.

Splits each frame into a spatial grid and records per-tile colour statistics. It is not a
semantic representation — it cannot tell a mug from a bowl — but it *is* a faithful
signature of **scene layout, colour and lighting**, which is precisely what
``coverage.scene_diversity`` needs to answer "are all these demonstrations in the same
scene?". It runs offline, in microseconds, with no weights and no torch.

Use ``--encoder dinov2`` when semantic similarity matters (different objects in the same
place, or the same object in different poses).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from bohrin._arrays import FloatArray

_GRID = 4


class TiledStatsEncoder:
    """Per-tile mean and standard deviation over a ``_GRID × _GRID`` spatial grid."""

    name = "tiled"

    def encode(self, frames: Sequence[FloatArray]) -> FloatArray:
        if not frames:
            return np.empty((0, 0), dtype=np.float64)
        return np.vstack([self._one(np.asarray(f, dtype=np.float64)) for f in frames])

    def _one(self, frame: FloatArray) -> FloatArray:
        if frame.ndim == 2:
            frame = frame[:, :, None]
        h, w = frame.shape[0], frame.shape[1]
        if h < _GRID or w < _GRID:
            return np.concatenate([frame.mean(axis=(0, 1)), frame.std(axis=(0, 1))])
        feats: list[float] = []
        for gy in range(_GRID):
            for gx in range(_GRID):
                tile = frame[
                    gy * h // _GRID : (gy + 1) * h // _GRID,
                    gx * w // _GRID : (gx + 1) * w // _GRID,
                ]
                feats.extend(tile.mean(axis=(0, 1)).tolist())
                feats.extend(tile.std(axis=(0, 1)).tolist())
        return np.asarray(feats, dtype=np.float64)
