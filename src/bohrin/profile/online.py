"""Single-pass online estimators — Stage ③ (docs/02 §3).

The profile is built in **one streaming pass** so a million-episode scan stays feasible:
detectors consume these precomputed statistics instead of re-reading the data. Two estimators
carry it: vectorized, numerically stable batch Welford for per-dimension mean/variance (plus
min/max and zero-fraction), and a uniform :class:`Reservoir` for everything rank-based.

**On quantiles, and why there is no sketch here.** q01/q50/q99 are estimated from the
reservoir rather than from a t-digest. That was originally recorded as a deferral, but the
measurement does not support implementing one: at 20 000 retained rows the reservoir estimates
q01/q99 to within **0.2 % rank error** on normal, log-normal and bimodal streams of two million
values (asserted in ``tests/test_streaming_scale.py``). A t-digest would be smaller, but it has
**no worst-case accuracy guarantee** — published adversarial inputs drive its error arbitrarily
high (Vesely et al., *Theory meets Practice at the Median*, KDD 2021) — so swapping a measured,
exactly-reproducible estimator for an unbounded-error one would weaken the guarantee to save
memory that is not scarce. If tail accuracy ever needs to *improve*, the replacement to reach
for is a KLL sketch, which does come with rank-error bounds; t-digest is not that upgrade.
"""

from __future__ import annotations

import numpy as np

from bohrin._arrays import FloatArray


class RunningMoments:
    """Per-dimension running mean/variance via the parallel (batch) Welford algorithm.

    Accepts data in ``(N, D)`` batches; combines each batch with the running aggregate in
    a numerically stable way (no catastrophic cancellation from a naive sum-of-squares).
    """

    __slots__ = ("_count", "_dim", "_m2", "_max", "_mean", "_min", "_zero")

    def __init__(self) -> None:
        self._count: int = 0
        self._dim: int | None = None
        self._mean: FloatArray = np.empty(0, dtype=np.float64)
        self._m2: FloatArray = np.empty(0, dtype=np.float64)
        self._min: FloatArray = np.empty(0, dtype=np.float64)
        self._max: FloatArray = np.empty(0, dtype=np.float64)
        self._zero: FloatArray = np.empty(0, dtype=np.float64)

    def update(self, batch: FloatArray) -> None:
        """Fold a ``(N, D)`` batch into the running aggregate."""
        x = np.asarray(batch, dtype=np.float64)
        if x.ndim != 2:
            raise ValueError(f"expected a 2-D (N, D) batch, got shape {x.shape}")
        n_b = x.shape[0]
        if n_b == 0:
            return
        if self._dim is None:
            self._init(x.shape[1])
        elif x.shape[1] != self._dim:
            raise ValueError(f"dimension mismatch: expected {self._dim}, got {x.shape[1]}")

        mean_b = x.mean(axis=0)
        m2_b = ((x - mean_b) ** 2).sum(axis=0)

        n_a = self._count
        n = n_a + n_b
        delta = mean_b - self._mean
        self._mean = self._mean + delta * (n_b / n)
        self._m2 = self._m2 + m2_b + (delta**2) * (n_a * n_b / n)
        self._count = n

        np.minimum(self._min, x.min(axis=0), out=self._min)
        np.maximum(self._max, x.max(axis=0), out=self._max)
        self._zero += (x == 0.0).sum(axis=0)

    def _init(self, dim: int) -> None:
        self._dim = dim
        self._mean = np.zeros(dim, dtype=np.float64)
        self._m2 = np.zeros(dim, dtype=np.float64)
        self._min = np.full(dim, np.inf, dtype=np.float64)
        self._max = np.full(dim, -np.inf, dtype=np.float64)
        self._zero = np.zeros(dim, dtype=np.float64)

    @property
    def count(self) -> int:
        """Total number of rows folded in."""
        return self._count

    @property
    def dim(self) -> int:
        """Dimensionality D (0 before any update)."""
        return self._dim or 0

    @property
    def mean(self) -> FloatArray:
        """Per-dimension mean."""
        return self._mean.copy()

    @property
    def variance(self) -> FloatArray:
        """Per-dimension population variance."""
        if self._count == 0:
            return self._m2.copy()
        return self._m2 / self._count

    @property
    def std(self) -> FloatArray:
        """Per-dimension population standard deviation."""
        return np.sqrt(self.variance)

    @property
    def min(self) -> FloatArray:
        """Per-dimension minimum."""
        return self._min.copy()

    @property
    def max(self) -> FloatArray:
        """Per-dimension maximum."""
        return self._max.copy()

    @property
    def zero_fraction(self) -> FloatArray:
        """Per-dimension fraction of exactly-zero values."""
        if self._count == 0:
            return self._zero.copy()
        return self._zero / self._count


class Reservoir:
    """Uniform streaming sample of rows via Vitter's Algorithm R (docs/02 §7).

    Holds at most ``capacity`` rows drawn uniformly at random from an arbitrarily long
    stream, in a single pass with O(capacity) memory. The draw is fully determined by the
    supplied generator, so a fixed seed yields a byte-identical sample (docs/02 §9). This
    is the bounded working set coverage/quantile estimators read instead of the full data.
    """

    __slots__ = ("_buf", "_capacity", "_dim", "_filled", "_rng", "_seen")

    def __init__(self, capacity: int, rng: np.random.Generator) -> None:
        if capacity <= 0:
            raise ValueError("reservoir capacity must be positive")
        self._capacity = capacity
        self._rng = rng
        self._seen = 0
        self._filled = 0
        self._dim: int | None = None
        #: Preallocated ``(capacity, D)`` buffer, created once the width is known. A flat array
        #: rather than a list of rows: no per-row object, and `values()` needs no vstack.
        self._buf: FloatArray | None = None

    def update(self, batch: FloatArray) -> None:
        """Fold a ``(N, D)`` batch into the reservoir.

        **Vectorized, and the reason is throughput on the streaming hot path.** The textbook
        formulation loops per row, which cost a Python iteration plus an RNG call for every
        step in the dataset — measured at ~1.4 M rows/s, so an OXE-scale mixture spent minutes
        here per channel before any detector ran.

        The draws are hoisted instead: Algorithm R accepts row ``i`` (0-based within the
        stream) with probability ``capacity / (seen + i + 1)``, and those Bernoulli trials are
        independent, so all ``N`` of them are drawn in **one** vectorized call. Only the
        *accepted* rows then need individual handling, and their expected count is
        ``O(capacity · log(N / capacity))`` — a few thousand even for a billion-row stream — so
        the remaining Python work is negligible. Later writes overwrite earlier ones exactly as
        the sequential version would, because the accepted rows are applied in stream order.
        """
        x = np.asarray(batch, dtype=np.float64)
        if x.ndim != 2:
            raise ValueError(f"expected a 2-D (N, D) batch, got shape {x.shape}")
        if self._dim is None:
            self._dim = x.shape[1]
            self._buf = np.empty((self._capacity, self._dim), dtype=np.float64)
        elif x.shape[1] != self._dim:
            raise ValueError(f"dimension mismatch: expected {self._dim}, got {x.shape[1]}")
        n = x.shape[0]
        if n == 0:
            return
        assert self._buf is not None

        # Phase 1 — fill empty slots straight from the batch.
        free = self._capacity - self._filled
        take = min(free, n)
        if take:
            self._buf[self._filled : self._filled + take] = x[:take]
            self._filled += take
            self._seen += take
        if take == n:
            return

        # Phase 2 — replacement. `positions[i]` is the number of rows seen once row i is
        # consumed, which is the denominator of that row's acceptance probability.
        rest = x[take:]
        positions = self._seen + 1 + np.arange(rest.shape[0], dtype=np.int64)
        draws = self._rng.integers(0, positions)
        accepted = np.flatnonzero(draws < self._capacity)
        for i in accepted.tolist():
            self._buf[int(draws[i])] = rest[i]
        self._seen += rest.shape[0]

    @property
    def seen(self) -> int:
        """Total rows observed (not just retained)."""
        return self._seen

    def values(self) -> FloatArray:
        """The retained sample as an ``(M, D)`` array (empty if nothing was seen)."""
        if self._buf is None or self._filled == 0:
            return np.empty((0, self._dim or 0), dtype=np.float64)
        return self._buf[: self._filled].copy()
