"""Lazy MP4 frame decoding for video-backed datasets (docs/03 §3, docs/05 §1, docs/09 §5).

LeRobot — the flagship format — does **not** store camera frames inline; it stores each
camera as an MP4 and references it from the Parquet rows. Without decoding those videos the
six VISION detectors and ``coverage.scene_diversity`` have nothing to look at. This module
is the bridge: it turns an on-disk MP4 into a sequence of :class:`~bohrin.ir.episode.LazyImage`
handles that decode a *single* frame only when a detector actually asks for it.

Two properties matter, and both are deliberate:

* **Lazy and bounded.** A stats-only scan touches no pixels, and a vision scan samples ~8
  frames per episode — so we decode ~8 frames per episode, not the whole clip. ``shape`` is
  known from the container without decoding, so gating (`has_images`) is free.
* **Optional dependency.** Decoding needs PyAV (``bohrin[video]``). It is imported lazily, so
  a proprio-only user never pays for it; :func:`available` lets the caller decide whether to
  attach video at all rather than crash a scan that never wanted pixels.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from bohrin._arrays import FloatArray
from bohrin.ir.episode import LazyImage


def available() -> bool:
    """Whether PyAV is importable — i.e. whether video can be decoded at all."""
    try:
        import av  # noqa: F401
    except ImportError:  # pragma: no cover - depends on the optional extra
        return False
    return True


def _av() -> Any:
    try:
        import av
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError("decoding video requires the optional dependency: pip install 'bohrin[video]'") from exc
    return av


@lru_cache(maxsize=64)
def _probe(path: str) -> tuple[int, int, int]:
    """(height, width, channels) of a video's first frame, cached per file.

    Reads only the container header and one frame, so gating stays cheap even across many
    cameras. Channels is 3 for the RGB we convert to; a decode failure yields a 1×1×3 stub
    so a corrupt file degrades to "tiny frame" rather than crashing the profile pass.
    """
    av = _av()
    try:
        with av.open(path) as container:
            stream = container.streams.video[0]
            height = int(stream.height or 0)
            width = int(stream.width or 0)
            if height and width:
                return (height, width, 3)
    except (OSError, StopIteration, IndexError, ValueError):  # pragma: no cover - corrupt file
        pass
    return (1, 1, 3)


@dataclass(frozen=True, slots=True)
class _VideoFrame:
    """A single decode-on-demand frame at ``frame_index`` in ``path``. A ``LazyImage``."""

    path: str
    frame_index: int
    _shape: tuple[int, int, int]

    @property
    def shape(self) -> tuple[int, int, int]:
        return self._shape

    def array(self) -> FloatArray:
        """Decode exactly this frame to an ``(H, W, 3)`` float64 RGB array.

        Seeks *backward* to the nearest keyframe, then decodes forward until the frame whose
        presentation timestamp maps to the target index — the pts-to-index conversion is what
        makes this correct on an inter-coded stream with sparse keyframes, where counting
        decoded frames from the keyframe would land on the wrong frame. A decode failure
        returns a black frame of the known shape, so one unreadable frame never crashes a
        scan (and reads, correctly, as a dropout to the vision detectors).
        """
        av = _av()
        try:
            with av.open(self.path) as container:
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"
                target = self.frame_index
                rate = stream.average_rate
                time_base = stream.time_base
                if rate and time_base:
                    container.seek(max(int(target / (rate * time_base)), 0), stream=stream, backward=True)
                last = None
                for frame in container.decode(stream):
                    last = frame
                    index = (
                        round(float(frame.pts * time_base * rate))
                        if (frame.pts is not None and rate and time_base)
                        else None
                    )
                    if index is None or index >= target:
                        return np.asarray(frame.to_ndarray(format="rgb24"), dtype=np.float64)
                if last is not None:  # target past the end → clamp to the final frame
                    return np.asarray(last.to_ndarray(format="rgb24"), dtype=np.float64)
        except (OSError, StopIteration, IndexError, ValueError):  # pragma: no cover - corrupt frame
            pass
        return np.zeros(self._shape, dtype=np.float64)


class VideoFrames(Sequence[LazyImage]):
    """A ``Sequence[LazyImage]`` over one camera's MP4, for a range of frame indices.

    ``length`` frames are exposed starting at ``start_frame`` — the offset lets a packed
    video (many episodes per file) expose just this episode's slice. Indexing is O(1) and
    allocates nothing; the decode happens in :meth:`_VideoFrame.array`.
    """

    def __init__(self, path: Path, *, length: int, start_frame: int = 0) -> None:
        self._path = str(path)
        self._length = max(0, length)
        self._start = max(0, start_frame)
        self._shape = _probe(self._path)

    def __len__(self) -> int:
        return self._length

    def __getitem__(self, index: int) -> LazyImage:  # type: ignore[override]
        # Detectors index by a single int (a sampled frame); slicing is unused, so the
        # Sequence ABC's slice contract is intentionally not implemented.
        if index < 0:
            index += self._length
        if not 0 <= index < self._length:
            raise IndexError(index)
        return _VideoFrame(self._path, self._start + index, self._shape)


def frames_for(path: Path, *, length: int, start_frame: int = 0) -> VideoFrames | None:
    """Build a :class:`VideoFrames` for ``path`` if it exists and PyAV is available, else ``None``.

    Returning ``None`` (rather than raising) is what lets the adapter attach video only when
    it can actually be decoded — a LeRobot dataset still scans fine for stats when
    ``bohrin[video]`` is not installed; the vision detectors simply have nothing to read, and
    the CLI surfaces that instead of failing.
    """
    if not available() or not path.is_file() or length <= 0:
        return None
    return VideoFrames(path, length=length, start_frame=start_frame)
