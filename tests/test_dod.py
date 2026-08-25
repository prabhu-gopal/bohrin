"""The Phase 0–2 Definition-of-Done checks that were specified but never asserted.

Each test here maps to a checkbox in ``docs/06_ROADMAP.md``. A DoD item that is not
executable is an item nobody can prove, so every remaining box is nailed down by a test:
the performance contract, the "show the defect" requirement, the honest handling of flags
that are accepted but not yet built, and the progress reporting the first-run UX promises.
"""

from __future__ import annotations

import time

import pytest

import _synth
import bohrin
from bohrin.api import scan
from bohrin.detectors._common import SERIES_POINTS, sparkline
from bohrin.detectors.stats import DeadDimensionDetector
from bohrin.policy.loader import UnreadablePolicyError
from bohrin.policy.target import UnknownTargetError
from bohrin.report.html import HtmlRenderer, _sparkline_svg
from bohrin.report.model import Evidence, Report
from bohrin.report.tty import TtyRenderer

# --------------------------------------------------------------------- performance (P1 DoD)


def test_ten_episode_scan_under_three_seconds() -> None:
    """docs/06 P1 DoD: a 10-episode set completes in < 3 s (docs/09 §1.3)."""
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=10))
    start = time.perf_counter()
    report = bohrin.scan(uri)
    elapsed = time.perf_counter() - start
    assert report.dataset.n_episodes == 10
    assert elapsed < 3.0, f"10-episode scan took {elapsed:.2f}s, DoD budget is 3.0s"


# ------------------------------------------------------------------- evidence series (docs/05 §5)


def test_sparkline_downsamples_and_preserves_extremes() -> None:
    values = [0.0] * 500 + [99.0] + [0.0] * 500
    out = sparkline(values, points=64)
    assert len(out) == 64
    # Index selection, not averaging: a downsampled spike must still be finite and bounded
    # by the source range — we never invent a value the signal did not contain.
    assert min(out) >= 0.0 and max(out) <= 99.0


def test_sparkline_is_bounded_and_drops_non_finite() -> None:
    assert sparkline([]) == []
    assert sparkline([float("nan"), float("inf"), 1.0]) == [1.0]
    assert len(sparkline(list(range(10_000)))) == SERIES_POINTS


def test_dead_dimension_ships_the_flat_line() -> None:
    """The headline P1 finding must carry the picture, not only the number."""
    episodes = _synth.inject_dead_dimension(_synth.clean_dataset(n_episodes=12), dim=2)
    findings = list(DeadDimensionDetector().run(_synth.build_context(episodes)))
    assert findings, "dead-dimension fixture must fire"
    series = findings[0].evidence.series
    assert len(series) > 1
    assert max(series) - min(series) == pytest.approx(0.0, abs=1e-9)  # flat, as claimed
    assert findings[0].evidence.series_label


def test_sparkline_svg_renders_constant_series_as_a_flat_line() -> None:
    svg = _sparkline_svg([3.0] * 8, "dead dim")
    assert "<polyline" in svg and "<script" not in svg
    ys = {p.split(",")[1] for p in svg.split('points="')[1].split('"')[0].split()}
    assert len(ys) == 1, "a constant signal must draw as one flat line"


def test_evidence_series_round_trips_through_json() -> None:
    """``series`` is part of the versioned L2 contract, so it must survive serialization."""
    report = _report_with_series()
    assert Report.from_json(report.to_json()).clusters[0].findings[0].evidence.series == [1.0, 2.0, 3.0]


def test_old_reports_without_series_still_load() -> None:
    """Schema 1.0 compatibility: ``series`` defaults, so pre-existing JSON stays readable."""
    report = _report_with_series()
    payload = report.model_dump(mode="json")
    ev = payload["clusters"][0]["findings"][0]["evidence"]
    del ev["series"], ev["series_label"]
    restored = Report.model_validate(payload)
    assert restored.clusters[0].findings[0].evidence.series == []


# ------------------------------------------------------------------------- report surfaces


def test_html_report_shows_evidence_locus_and_headline() -> None:
    html = HtmlRenderer().render(_report_with_series())
    assert "<svg" in html and "<polyline" in html  # the defect is drawn
    assert "headline" in html  # depth-1 summary present
    assert "Provenance" in html and "Where" in html  # depth-3 completeness
    assert "http://" not in html and "https://" not in html  # still self-contained
    assert "<script" not in html  # no JS: renders in any offline viewer


def test_html_escapes_hostile_content() -> None:
    """Titles come from data (episode ids, task strings) — they must never inject markup."""
    report = _report_with_series(title="<img src=x onerror=alert(1)>")
    html = HtmlRenderer().render(report)
    assert "<img src=x" not in html
    assert "&lt;img" in html


def test_tty_gives_every_shown_cluster_a_fix_not_just_the_top_one() -> None:
    report = _report_with_series(n_clusters=3)
    text = TtyRenderer().render(report)
    assert len(report.clusters) > 1, "fixture must produce more than the top cluster"
    for c in report.clusters:
        assert c.title in text
    # One recommendation arrow per rendered cluster — not just for the top one (docs/05 §2).
    assert text.count("→") == len(report.clusters)
    assert "MEDIUM▸" not in text, "severity column must stay padded"
    assert "--html report.html" in text  # the 'Next:' nudge


# ------------------------------------------------- honesty: flags accepted but not yet built


def test_policy_flag_is_no_longer_silently_ignored() -> None:
    """P3 built the POLICY↔DATA family, so --policy now *acts* instead of refusing.

    The rule this replaced still holds: a flag must never be accepted and ignored. Here
    that means a bad checkpoint path raises rather than yielding a clean report.
    """
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=8))
    with pytest.raises(UnreadablePolicyError):
        scan(uri, policy="./definitely-not-a-checkpoint.safetensors")


def test_target_flag_is_validated_not_ignored() -> None:
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=8))
    with pytest.raises(UnknownTargetError):
        scan(uri, target="not-a-real-family")


# ------------------------------------------------------------------------------- progress


def test_progress_is_reported_and_cannot_change_the_result() -> None:
    uri = _synth.register_memory_dataset(_synth.clean_dataset(n_episodes=8))
    events: list[tuple[str, int, int | None]] = []
    with_progress = bohrin.scan(uri, progress=lambda s, d, t: events.append((s, d, t)))
    without = bohrin.scan(uri)

    stages = {e[0] for e in events}
    assert stages == {"profile", "detect"}
    assert [e[1] for e in events if e[0] == "profile"] == list(range(1, 9))  # monotonic
    assert with_progress.to_json() == without.to_json(), "progress is presentation only"


# ----------------------------------------------------------------------------------- utils


def _report_with_series(*, title: str = "Action dim 2 never moves", n_clusters: int = 1) -> Report:
    """A small report carrying an evidence series, built through the real pipeline."""
    episodes = _synth.inject_dead_dimension(_synth.clean_dataset(n_episodes=10), dim=2)
    uri = _synth.register_memory_dataset(episodes)
    report = bohrin.scan(uri)
    assert report.clusters, "fixture must produce findings"
    clusters = report.clusters[:n_clusters]
    first = clusters[0]
    findings = list(first.findings)
    findings[0] = findings[0].model_copy(
        update={"title": title, "evidence": Evidence(series=[1.0, 2.0, 3.0], series_label="demo")}
    )
    clusters = [first.model_copy(update={"title": title, "findings": findings}), *clusters[1:]]
    return report.model_copy(update={"clusters": clusters})
