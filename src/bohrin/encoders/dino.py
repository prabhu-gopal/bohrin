"""Frozen DINOv2 visual features — opt-in via ``bohrin[vision]`` (docs/09 §5).

DINOv2 is the reference frozen backbone for robot-manipulation perception: transferable
features for recognition- and geometry-sensitive tasks, used as a frozen encoder with
minimal heads (nearest-neighbour memory banks, linear probes) across recent manipulation
work. We use it exactly that way — **frozen, inference-only, embeddings only**. Nothing is
trained and no gradients are taken.

Deliberate design choices:

* **Never selected implicitly.** Instantiating this downloads model weights, so it requires
  an explicit ``--encoder dinov2``. Silent network access would violate the local-first
  principle (docs/00 §5).
* **Lazy import.** ``torch`` is only imported inside ``encode``/``__init__``, so the core
  install never pays for it and mypy never needs torch stubs.
* ViT-S/14 is the default: the smallest DINOv2 variant, CPU-feasible for the sampled frames
  Layer 1 decodes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from bohrin._arrays import FloatArray

_MODEL = "dinov2_vits14"
_PATCH = 14
_SIZE = 224  # multiple of the patch size


class DinoV2Encoder:
    """Frozen DINOv2 ViT-S/14 CLS embeddings (requires ``bohrin[vision]``)."""

    name = "dinov2"

    def __init__(self, model: str = _MODEL) -> None:
        self._model_name = model
        self._torch: Any | None = None
        self._model: Any | None = None

    def _load(self) -> tuple[Any, Any]:
        if self._model is None:
            try:
                import torch
            except ImportError as exc:  # pragma: no cover - depends on optional extra
                raise RuntimeError(
                    "The dinov2 encoder requires the vision extra: pip install 'bohrin[vision]'"
                ) from exc
            model = torch.hub.load("facebookresearch/dinov2", self._model_name)
            model.eval()
            self._torch = torch
            self._model = model
        assert self._torch is not None and self._model is not None
        return self._torch, self._model

    def encode(self, frames: Sequence[FloatArray]) -> FloatArray:
        if not frames:
            return np.empty((0, 0), dtype=np.float64)
        torch, model = self._load()
        batch = np.stack([_prepare(np.asarray(f, dtype=np.float64)) for f in frames])
        tensor = torch.from_numpy(batch).float().permute(0, 3, 1, 2)
        with torch.inference_mode():
            out = model(tensor)
        embeddings: FloatArray = out.cpu().numpy().astype(np.float64)
        return embeddings


def _prepare(frame: FloatArray) -> FloatArray:
    """Resize (nearest, dependency-free) to the model's input size and scale to [0, 1]."""
    if frame.ndim == 2:
        frame = np.repeat(frame[:, :, None], 3, axis=2)
    if frame.shape[2] == 1:
        frame = np.repeat(frame, 3, axis=2)
    h, w, _ = frame.shape
    ys = (np.linspace(0, h - 1, _SIZE)).astype(int)
    xs = (np.linspace(0, w - 1, _SIZE)).astype(int)
    resized: FloatArray = frame[np.ix_(ys, xs)][:, :, :3]
    scale = 255.0 if resized.max() > 1.0 else 1.0
    return resized / scale
