"""Triage-by-default: a first run stays fast on a large dataset (docs/05 §3).

The promise is "triage-by-default, ``--full`` on demand": a zero-flag scan of a huge dataset
must not silently grind through every episode, and must *say* it sampled. These tests pin
that behavior — the default caps, ``--full`` removes the cap, and the sampling is surfaced,
not hidden.
"""

from __future__ import annotations

import _synth
import bohrin
from bohrin.config import DEFAULT_TRIAGE_EPISODES, ScanConfig
from bohrin.report.tty import TtyRenderer

_BIG = DEFAULT_TRIAGE_EPISODES + 120


def test_default_scan_triages_a_large_dataset() -> None:
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=_BIG))
    report = bohrin.scan(uri)
    assert report.dataset.n_episodes == DEFAULT_TRIAGE_EPISODES
    assert report.dataset.total_episodes == _BIG
    assert report.dataset.sampled


def test_full_scans_every_episode() -> None:
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=_BIG))
    report = bohrin.scan(uri, full=True)
    assert report.dataset.n_episodes == _BIG
    assert not report.dataset.sampled


def test_explicit_sample_episodes_overrides_the_default() -> None:
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=_BIG))
    report = bohrin.scan(uri, sample_episodes=50)
    assert report.dataset.n_episodes == 50
    assert report.dataset.sampled


def test_small_dataset_is_never_marked_sampled() -> None:
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=16))
    report = bohrin.scan(uri)
    assert report.dataset.n_episodes == 16
    assert report.dataset.total_episodes == 16
    assert not report.dataset.sampled


def test_triage_is_reproducible() -> None:
    """The sampled subset is seeded, so a triage scan is as deterministic as a full one."""
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=_BIG))
    assert bohrin.scan(uri).to_json() == bohrin.scan(uri).to_json()


def test_tty_announces_the_triage() -> None:
    uri = _synth.register_memory_dataset(_synth.inject_dead_dimension(_synth.clean_dataset(n_episodes=_BIG), dim=2))
    report = bohrin.scan(uri)
    text = TtyRenderer().render(report)
    assert "triage" in text.lower()
    assert "--full" in text


def test_max_episodes_contract() -> None:
    assert ScanConfig(path="x").max_episodes() == DEFAULT_TRIAGE_EPISODES
    assert ScanConfig(path="x", full=True).max_episodes() is None
    assert ScanConfig(path="x", sample_episodes=10).max_episodes() == 10


def test_tty_points_at_the_flags_that_unlock_the_policy_checks() -> None:
    """A default scan skips the POLICY<->DATA family and used to say nothing about it.

    Those five checks need a model to compare against, so they are correctly silent without
    one — but silence made `--target` and `--policy` undiscoverable: the only way to learn
    the checks existed was to read `--help`. The hint appears exactly when none of them ran.
    """
    episodes = _synth.clean_dataset(n_episodes=8)
    uri = _synth.register_memory_dataset(episodes)

    text = TtyRenderer().render(bohrin.scan(uri))
    assert "--target" in text and "--policy" in text

    targeted = bohrin.scan(uri, target="act")
    if any(d.startswith("policy_data.") for d in targeted.detectors_run):
        assert "--target" not in TtyRenderer().render(targeted)
