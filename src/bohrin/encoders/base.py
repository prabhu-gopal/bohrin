"""The visual-encoder seam (docs/09 §5).

Coverage and OOD reasoning is far stronger with a visual representation than with
proprioception alone — *Data Scaling Laws* (ICLR 2025 Oral) shows generalization scales with
the diversity of **scenes and objects**, which only pixels can tell you about.

This module defines the seam so the encoder is a swappable strategy rather than a hard
dependency:

* :class:`VisualEncoder` — the protocol. One method, ``encode``.
* The **default is zero-dependency and offline** (:class:`~bohrin.encoders.tiled.TiledStatsEncoder`),
  honouring the local-first principle: no weights download, no network, works everywhere.
* A **frozen DINOv2** backend is opt-in via ``bohrin[vision]`` and ``--encoder dinov2``. It is
  never selected implicitly, because loading it fetches model weights and that must be the
  user's explicit choice.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from bohrin._arrays import FloatArray


@runtime_checkable
class VisualEncoder(Protocol):
    """Turns frames into a fixed-length embedding per frame."""

    #: Stable identifier, e.g. ``"tiled"`` / ``"dinov2"``.
    name: str

    def encode(self, frames: Sequence[FloatArray]) -> FloatArray:
        """Encode ``N`` ``(H, W, C)`` frames into an ``(N, D)`` embedding matrix."""
        ...
