"""The catalogue must not drift from the registry (docs/04, principle 7).

``04_DETECTORS.md`` describes the *target* battery. Three of its entries are deliberately not
implemented, and the risk with a deliberate deferral is that it quietly becomes an accident: the
reason ages out of anyone's memory, and either the check gets built badly or the gap gets
forgotten. This suite pins both directions — the deferred ids are absent from the registry, and
each one still has a stated reason in the docs.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import _synth
from bohrin.detectors.registry import discover as discover_detectors
from bohrin.ir.episode import Episode

#: Catalogued in `04_DETECTORS.md` but deliberately unbuilt, with why.
#:
#: These are refusals, not backlog. Principle 7 forbids shipping a check whose threshold cannot
#: be falsified, because a detector that fires on healthy data costs more trust than a missing
#: detector costs coverage.
DEFERRED: dict[str, str] = {
    "coverage.state_space_density": (
        "No formulation separates a genuinely thin state cloud from ordinary data. Measured "
        "(see test_the_state_space_density_deferral_is_still_justified): a probe-to-nearest-state "
        "gap ratio scores broad fixtures 5.9-17.2 and thin ones 7.8-825, so the classes overlap "
        "and the statistic tracks the cloud's ambient extent rather than its thinness. Every "
        "trajectory is locally one-dimensional, which is what defeats the obvious framings; the "
        "ones that avoid it merely restate coverage.mode_collapse."
    ),
    "label.inconsistent_phrasing": (
        "Requires distinguishing paraphrase from genuinely different meaning, which needs a text "
        "embedding. DROID collects three phrasings per episode on purpose, so flagging paraphrase "
        "would report a best practice as a defect. Purely geometric proxies failed to separate the "
        "classes at all (27.5 vs 27.1 on the same statistic)."
    ),
    "smoothness.effort_manipulability": (
        "Needs a per-embodiment robot model (URDF) to compute joint effort and manipulability. "
        "Without one the quantities are undefined, not merely imprecise. Scheduled for P5 with the "
        "robot-model zoo."
    ),
}


def test_the_deferred_detectors_are_genuinely_absent() -> None:
    """If one gets built, it must be removed from DEFERRED and given a benchmark scenario."""
    registered = {d.id for d in discover_detectors()}
    built = sorted(registered & set(DEFERRED))
    assert not built, (
        f"{built} are implemented but still listed as deferred. Remove them from DEFERRED and add "
        f"a Scenario in test_benchmark.py so their error rates are measured."
    )


def test_every_deferral_states_a_reason() -> None:
    for detector_id, reason in DEFERRED.items():
        assert len(reason) > 80, f"DEFERRED[{detector_id}] needs a real reason, got {reason!r}"


def test_the_docs_still_mark_the_deferred_detectors() -> None:
    """A deferral recorded only in a test is a deferral users cannot discover."""
    catalogue = Path(__file__).resolve().parents[1] / "docs" / "04_DETECTORS.md"
    if not catalogue.is_file():  # pragma: no cover - docs ship with the repo
        pytest.skip("catalogue not present")
    text = catalogue.read_text(encoding="utf-8")
    for detector_id in DEFERRED:
        assert detector_id in text, f"{detector_id} is deferred but not described in 04_DETECTORS.md"


def test_the_state_space_density_deferral_is_still_justified() -> None:
    """The measurement behind the refusal, kept runnable rather than remembered.

    A state-space *density* check needs a statistic that is high for thin coverage and low for
    broad coverage. The most promising scale-free candidate is the median distance from random
    probes in the state cloud's principal box to the nearest demonstrated state, normalized by
    the typical spacing between demonstrated states.

    It does not separate the classes: a narrow-initial-condition dataset (genuinely thin) scores
    *below* an ordinary one. If a future formulation does separate them, this test fails — which
    is the intended signal to go build the detector.
    """
    from bohrin.analysis import embeddings
    from bohrin.analysis.neighbors import knn

    def gap_ratio(episodes: list[Episode], probes: int = 400) -> float | None:
        rng = np.random.default_rng(1)
        states = np.vstack([embeddings.trajectory(ep) for ep in episodes])
        if states.shape[0] < 20:
            return None
        centred = states - states.mean(axis=0)
        _, _, basis = np.linalg.svd(centred, full_matrices=False)
        k = min(3, basis.shape[0])
        projected = centred @ basis[:k].T
        probe = rng.uniform(projected.min(axis=0), projected.max(axis=0), size=(probes, k))
        to_nearest = np.min(np.linalg.norm(probe[:, None, :] - projected[None, :, :], axis=2), axis=1)
        spacing = float(np.median(knn(projected, 1)[0][:, 0]))
        if spacing <= 1e-12:
            return None
        return float(np.median(to_nearest) / spacing)

    broad = [
        gap_ratio(_synth.clean_dataset(n_episodes=24, length=60)),
        gap_ratio(_synth.smooth_dataset(n_episodes=24)),
        gap_ratio(_synth.wandering_dataset(n_episodes=24, wander_at=())),
    ]
    thin = [
        gap_ratio(_synth.single_strategy_dataset(n_episodes=24)),
        gap_ratio(_synth.narrow_init_dataset(n_episodes=24)),
        gap_ratio(_synth.two_style_dataset(n_episodes=24)),
    ]
    broad_values = [v for v in broad if v is not None]
    thin_values = [v for v in thin if v is not None]
    assert broad_values and thin_values

    assert min(thin_values) <= max(broad_values), (
        "the probe-gap statistic now separates thin from broad coverage "
        f"(thin ≥ {min(thin_values):.2f} > broad ≤ {max(broad_values):.2f}). "
        "coverage.state_space_density has become falsifiable — build it, remove it from DEFERRED, "
        "and give it a benchmark scenario."
    )
