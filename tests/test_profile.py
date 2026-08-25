"""The online estimators match a batch numpy computation (docs/02 §3)."""

from __future__ import annotations

import numpy as np

from bohrin.profile.online import RunningMoments


def test_batch_welford_matches_numpy() -> None:
    rng = np.random.default_rng(0)
    data = rng.normal(3.0, 2.0, size=(1000, 5))

    rm = RunningMoments()
    for chunk in np.array_split(data, 7):  # fold in uneven batches
        rm.update(chunk)

    assert rm.count == 1000
    np.testing.assert_allclose(rm.mean, data.mean(axis=0), rtol=1e-10)
    np.testing.assert_allclose(rm.std, data.std(axis=0), rtol=1e-10)
    np.testing.assert_allclose(rm.min, data.min(axis=0))
    np.testing.assert_allclose(rm.max, data.max(axis=0))


def test_zero_fraction_and_constant_dimension() -> None:
    data = np.ones((10, 3))
    data[:, 1] = 0.0  # a constant-zero channel
    rm = RunningMoments()
    rm.update(data)

    assert rm.std[1] == 0.0
    assert rm.zero_fraction[1] == 1.0
    assert rm.zero_fraction[0] == 0.0


def test_empty_batch_is_a_noop() -> None:
    rm = RunningMoments()
    rm.update(np.empty((0, 4)))
    assert rm.count == 0
