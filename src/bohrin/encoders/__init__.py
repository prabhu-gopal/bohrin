"""Visual encoders — the swappable representation behind vision-aware coverage (docs/09 §5).

``get_encoder`` is the single entry point. The default is offline and dependency-free; the
DINOv2 backend must be asked for by name, because loading it downloads weights.
"""

from __future__ import annotations

from bohrin.encoders.base import VisualEncoder
from bohrin.encoders.tiled import TiledStatsEncoder

DEFAULT_ENCODER = "tiled"


def get_encoder(name: str = DEFAULT_ENCODER) -> VisualEncoder:
    """Return the named encoder.

    ``"tiled"`` (default) is zero-dependency and offline. ``"dinov2"`` loads frozen DINOv2
    features and requires ``bohrin[vision]``; it is never chosen implicitly.
    """
    key = (name or DEFAULT_ENCODER).strip().lower()
    if key in {"", "tiled", "default"}:
        return TiledStatsEncoder()
    if key in {"dinov2", "dino"}:
        from bohrin.encoders.dino import DinoV2Encoder  # lazy: keeps torch out of the core

        return DinoV2Encoder()
    raise ValueError(f"unknown encoder {name!r}; available: tiled, dinov2")


__all__ = ["DEFAULT_ENCODER", "TiledStatsEncoder", "VisualEncoder", "get_encoder"]
