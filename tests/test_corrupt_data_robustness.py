"""A scan must survive corrupt data, because corrupt data is the point (docs/04 §A).

NaN and ±inf are among the most common real-world defects — ``integrity.nan_inf`` exists
precisely to report them. But the solvers underneath the battery reject them: ``numpy.linalg.
lstsq`` raises ``LinAlgError``, and scikit-learn's ``Ridge``, ``KMeans``, ``NearestNeighbors``
and ``KNeighborsClassifier`` all raise ``ValueError``. **Six detectors crashed the entire scan
on a single NaN**, which is the worst possible failure mode for this tool: the user loses the
report that would have told them about the NaN.

The contract asserted here is that a corrupt row is *excluded from analysis*, not fatal to it —
the corruption is already reported by INTEGRITY, and the rest of the data still deserves to be
checked. Where a row index is mapped back to an episode (so a finding can name it), the arrays
are filtered **jointly**, because renumbering one side alone would accuse the wrong episode.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Iterator

import numpy as np
import pytest

import _synth
from bohrin.analysis.robust import finite_row_mask, keep_finite_rows
from bohrin.api import scan
from bohrin.detectors.registry import discover as discover_detectors
from bohrin.ir.episode import Episode
from bohrin.ir.schema import DatasetSchema


def _nan_action(episodes: list[Episode], index: int, *, value: float = np.nan) -> list[Episode]:
    action = np.array(episodes[index].steps.action, dtype=np.float64)
    action[4, 1] = value
    episodes[index] = _synth._set_action(episodes[index], action)
    return episodes


def _single_nan() -> list[Episode]:
    return _nan_action(_synth.clean_dataset(n_episodes=14), 3)


def _single_inf() -> list[Episode]:
    return _nan_action(_synth.clean_dataset(n_episodes=14), 2, value=np.inf)


def _nan_in_every_episode() -> list[Episode]:
    episodes = _synth.clean_dataset(n_episodes=14)
    for i in range(len(episodes)):
        action = np.array(episodes[i].steps.action, dtype=np.float64)
        action[::7, :] = np.nan
        episodes[i] = _synth._set_action(episodes[i], action)
    return episodes


def _nan_in_start_states() -> list[Episode]:
    """Hits the neighbour searches keyed on each episode's *first* state."""
    episodes = _synth.labelled_dataset()
    for i in (0, 1):
        proprio = np.array(episodes[i].steps.proprio, dtype=np.float64)
        proprio[0, :] = np.nan
        episodes[i] = _synth._set_proprio(episodes[i], proprio)
    return episodes


def _wholly_nan_episodes() -> list[Episode]:
    """An entire episode of NaN — the metric-vector path (KMeans) rather than a single row."""
    episodes = _synth.two_style_dataset()
    for i in (0, 3):
        proprio = np.array(episodes[i].steps.proprio, dtype=np.float64)
        proprio[:] = np.nan
        episodes[i] = _synth._set_proprio(episodes[i], proprio)
    return episodes


#: ``(name, builder, schema)`` — schema only where cameras must be declared.
CORRUPTIONS: list[tuple[str, Callable[[], list[Episode]], DatasetSchema | None]] = [
    ("single NaN", _single_nan, None),
    ("single inf", _single_inf, None),
    ("NaN in every episode", _nan_in_every_episode, None),
    ("NaN in start states", _nan_in_start_states, None),
    ("wholly NaN episodes", _wholly_nan_episodes, None),
    ("NaN with cameras", lambda: _nan_action(_synth.vision_dataset(), 1), _synth.vision_schema()),
]


def _cases() -> Iterator[tuple[str, list[Episode], DatasetSchema | None]]:
    for name, builder, schema in CORRUPTIONS:
        yield name, builder(), schema


@pytest.mark.parametrize(("name", "builder", "schema"), CORRUPTIONS, ids=[c[0] for c in CORRUPTIONS])
def test_no_detector_crashes_on_corrupt_data(
    name: str,
    builder: Callable[[], list[Episode]],
    schema: DatasetSchema | None,
) -> None:
    """Every applicable detector must return findings or nothing — never raise."""
    episodes = builder()
    ctx = _synth.build_context(episodes, schema=schema) if schema else _synth.build_context(episodes)
    crashed: list[str] = []
    for detector in discover_detectors():
        if not detector.applicable(ctx.profile, ctx.policy):
            continue
        try:
            list(detector.run(ctx))
        except Exception as exc:  # the point of the test is that nothing escapes
            crashed.append(f"{detector.id}: {type(exc).__name__}: {exc}")
    assert not crashed, f"{name} crashed {len(crashed)} detector(s):\n" + "\n".join(crashed)


@pytest.mark.parametrize(("name", "builder", "schema"), CORRUPTIONS, ids=[c[0] for c in CORRUPTIONS])
def test_a_full_scan_completes_on_corrupt_data(
    name: str,
    builder: Callable[[], list[Episode]],
    schema: DatasetSchema | None,
) -> None:
    """End to end: the report the user needs must actually be produced."""
    episodes = builder()
    path = (
        _synth.register_memory_dataset(episodes, schema=schema) if schema else _synth.register_memory_dataset(episodes)
    )
    report = scan(path)
    assert report.clusters, f"{name} produced no findings at all — the corruption went unreported"
    assert report.to_json(), f"{name} produced a report that would not serialize"


def test_the_corruption_itself_is_reported() -> None:
    """Robustness must not become silence: NaN is still a HIGH finding."""
    report = scan(_synth.register_memory_dataset(_single_nan()))
    cluster = report.cluster("integrity.nan_inf")
    assert cluster is not None, "a NaN was tolerated so thoroughly that nobody mentioned it"


def test_corrupt_rows_do_not_change_the_verdict_on_the_clean_remainder() -> None:
    """Dropping corrupt rows must not manufacture or suppress findings elsewhere.

    A dataset with one NaN cell should report essentially what the clean dataset reports, plus
    the NaN — if excluding that row shifted every other detector's conclusion, "ignore the bad
    row" would not be a safe policy.
    """
    clean = _synth.clean_dataset(n_episodes=14)
    corrupt = _nan_action(_synth.clean_dataset(n_episodes=14), 3)

    clean_ids = {c.id for c in scan(_synth.register_memory_dataset(clean)).clusters}
    corrupt_ids = {c.id for c in scan(_synth.register_memory_dataset(corrupt)).clusters}
    new = corrupt_ids - clean_ids - {"integrity.nan_inf"}
    assert not new, f"tolerating a NaN introduced unrelated findings: {sorted(new)}"


# --------------------------------------------------------------------- the primitives


def test_finite_row_mask_requires_every_array_to_be_finite() -> None:
    a = np.array([[1.0, 2.0], [3.0, np.nan], [5.0, 6.0]])
    b = np.array([1.0, 2.0, np.inf])
    assert finite_row_mask(a).tolist() == [True, False, True]
    assert finite_row_mask(a, b).tolist() == [True, False, False]


def test_keep_finite_rows_preserves_alignment() -> None:
    features = np.array([[1.0], [np.nan], [3.0], [4.0]])
    targets = np.array([[10.0], [20.0], [30.0], [np.inf]])
    kept_features, kept_targets = keep_finite_rows(features, targets)
    assert kept_features.ravel().tolist() == [1.0, 3.0]
    assert kept_targets.ravel().tolist() == [10.0, 30.0]


def test_keep_finite_rows_on_all_finite_input_is_a_no_op() -> None:
    a = np.array([[1.0, 2.0], [3.0, 4.0]])
    (kept,) = keep_finite_rows(a)
    assert np.array_equal(kept, a)


def test_keep_finite_rows_can_return_nothing() -> None:
    a = np.array([[np.nan], [np.inf]])
    (kept,) = keep_finite_rows(a)
    assert kept.shape[0] == 0


def test_a_scan_of_corrupt_data_emits_no_numpy_warnings() -> None:
    """A scan must not spray ``RuntimeWarning`` at the user.

    Every one of these warnings marked a place where a non-finite value was silently flowing
    into a statistic — so they were a symptom, not cosmetics. Asserting their absence keeps the
    NaN handling from being quietly re-broken by a future aggregate that forgets to filter.
    """
    for name, episodes, schema in _cases():
        path = (
            _synth.register_memory_dataset(episodes, schema=schema)
            if schema
            else _synth.register_memory_dataset(episodes)
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            try:
                scan(path)
            except RuntimeWarning as exc:  # pragma: no cover - only on regression
                pytest.fail(f"{name} produced a numpy RuntimeWarning during the scan: {exc}")
