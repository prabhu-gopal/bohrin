"""The bounded working set of raw episodes detectors inspect (docs/02 §7, docs/09 §1).

Most detectors read the :class:`~bohrin.profile.dataset_profile.DatasetProfile`, but the
COVERAGE / CONSISTENCY / DYNAMICS families need whole trajectories, so a subset of episodes is
held in RAM. Two things went wrong with holding "the first 5000", and both matter at scale:

**It was unbounded in bytes.** 5000 episodes is a *count*, and an episode's footprint is
``T × D × 8`` per channel. Measured: at ``T=5000, D=32`` the cap admits **12.8 GB** — a scan
that dies on the machine it was supposed to help. The bound that matters is memory, so this
reservoir enforces a byte budget as well as a count.

**It was a prefix, not a sample.** Keeping the first N episodes of a larger stream biases the
working set toward the start of collection, which is exactly wrong for the detectors that read
it: ``stats.distribution_drift`` compares the first half of the reservoir against the second to
find mid-collection shifts, so on any dataset larger than the cap it was comparing the first
quarter against the second quarter and calling that "the whole collection". This class uses
Vitter's Algorithm R, so the retained episodes are a **uniform** sample of everything streamed,
and the ``--seed`` makes the choice reproducible.

Eviction under the byte budget keeps the reservoir *uniform*, not merely small: a replaced slot
is chosen the same way Algorithm R chooses one, so the surviving set stays an unbiased sample
of the stream rather than "whatever happened to be small enough".
"""

from __future__ import annotations

import numpy as np

from bohrin.ir.episode import Episode

#: Default RAM budget for retained episodes. Chosen to stay comfortably inside a laptop's
#: working set while admitting a statistically useful sample of a large dataset; override with
#: ``--max-episode-memory``.
DEFAULT_MEMORY_BUDGET_MB = 1024


def episode_nbytes(episode: Episode) -> int:
    """Bytes of array payload one episode holds in RAM.

    Counts the numeric columns actually retained. Lazily-decoded images are excluded on
    purpose: they are file handles until a detector asks for a frame, so charging their
    decoded size here would refuse episodes whose pixels may never be read.
    """
    steps = episode.steps
    total = 0
    for column in (steps.action, steps.proprio, steps.timestamp, steps.reward):
        if column is not None:
            total += int(np.asarray(column).nbytes)
    return total


class EpisodeReservoir:
    """A uniform sample of streamed episodes, bounded by both count and total bytes."""

    __slots__ = ("_budget_bytes", "_capacity", "_dropped_for_memory", "_held", "_nbytes", "_rng", "_seen")

    def __init__(self, capacity: int, budget_bytes: int, rng: np.random.Generator) -> None:
        if capacity <= 0:
            raise ValueError("episode reservoir capacity must be positive")
        if budget_bytes <= 0:
            raise ValueError("episode reservoir byte budget must be positive")
        self._capacity = capacity
        self._budget_bytes = budget_bytes
        self._rng = rng
        self._held: list[Episode] = []
        self._nbytes = 0
        self._seen = 0
        self._dropped_for_memory = 0

    def add(self, episode: Episode) -> None:
        """Offer one episode to the reservoir (Algorithm R, under a byte budget)."""
        self._seen += 1
        size = episode_nbytes(episode)

        # Phase 1: still filling, and it fits.
        if len(self._held) < self._capacity and self._nbytes + size <= self._budget_bytes:
            self._held.append(episode)
            self._nbytes += size
            return

        # Phase 2: full (by count or by bytes). Algorithm R replaces slot j with probability
        # capacity/seen, which is what keeps the retained set uniform over the whole stream.
        # The effective capacity is however many episodes the budget actually allowed, so the
        # replacement probability stays consistent with the set we are maintaining.
        effective = len(self._held)
        if effective == 0:  # a single episode larger than the whole budget: keep it anyway,
            self._held.append(episode)  # since an empty reservoir would disable half the battery
            self._nbytes += size
            return
        j = int(self._rng.integers(0, self._seen))
        if j >= effective:
            self._dropped_for_memory += int(self._nbytes + size > self._budget_bytes)
            return
        # Only swap when the replacement keeps us inside the budget; otherwise this episode
        # loses its draw, which biases nothing because the draw was independent of its size.
        if self._nbytes - episode_nbytes(self._held[j]) + size > self._budget_bytes:
            self._dropped_for_memory += 1
            return
        self._nbytes += size - episode_nbytes(self._held[j])
        self._held[j] = episode

    @property
    def episodes(self) -> list[Episode]:
        """The retained episodes, in stream order."""
        return self._held

    @property
    def nbytes(self) -> int:
        """Bytes currently held."""
        return self._nbytes

    @property
    def seen(self) -> int:
        """Episodes offered to the reservoir."""
        return self._seen

    @property
    def truncated(self) -> bool:
        """Whether the reservoir holds fewer episodes than were streamed.

        Surfaced so the report can say the trajectory-level families saw a sample — silence
        here would let a user read "no coverage findings" as "coverage is fine" when the
        coverage detectors only ever saw part of the data.
        """
        return len(self._held) < self._seen

    @property
    def dropped_for_memory(self) -> int:
        """Episodes declined specifically because the byte budget was exhausted."""
        return self._dropped_for_memory
