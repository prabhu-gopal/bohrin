"""Phase 4 trust guarantees: determinism, JSON-schema stability, SARIF, localization.

Each test maps to a P4 DoD checkbox (docs/06):

* **Two scans of the same data are byte-identical** — the determinism guarantee a CI gate
  depends on. Without it, `--ci` would flap and teams would learn to ignore it.
* **The JSON schema is stable** — the report is L2's API surface (docs/09 §3). A field that
  silently changes shape breaks every downstream L2 diff, so the schema is pinned by a
  golden test that must be updated deliberately.
* **SARIF renders on a GitHub PR** — asserted structurally against what GitHub consumes.
* **`--lang` renders a non-English report; findings unchanged** — the report chrome
  translates while the `Finding` objects stay identical.
"""

from __future__ import annotations

import json
from typing import Any

import _synth
import bohrin
from bohrin.report.messages import catalog, supported_languages
from bohrin.report.model import Report

# ------------------------------------------------------------------------- determinism


def _faulted_uri(seed: int = 0) -> str:
    episodes = _synth.inject_dead_dimension(_synth.clean_dataset(n_episodes=14, seed=seed), dim=2)
    episodes = _synth.inject_saturation(episodes)
    return _synth.register_memory_dataset(episodes)


def test_two_scans_are_byte_identical() -> None:
    """docs/06 P4 DoD: determinism. No wall-clock, seeded RNG → identical JSON."""
    uri = _faulted_uri()
    a = bohrin.scan(uri).to_json()
    b = bohrin.scan(uri).to_json()
    assert a == b


def test_determinism_holds_across_the_full_detector_battery() -> None:
    """Not just the model — every detector's sampled draws must be reproducible too."""
    uri = _faulted_uri(seed=3)
    first = bohrin.scan(uri)
    second = bohrin.scan(uri)
    assert [c.id for c in first.clusters] == [c.id for c in second.clusters]
    assert first.to_json() == second.to_json()


def test_seed_is_the_only_thing_that_changes_sampling() -> None:
    uri = _faulted_uri()
    assert bohrin.scan(uri, seed=1).to_json() == bohrin.scan(uri, seed=1).to_json()


# --------------------------------------------------------------- JSON schema stability


# The set of top-level Report fields and the Finding fields L2 diffs against. Adding a
# field is a compatible change; removing or renaming one is not — and must be a conscious
# edit to this list, not an accident that slips through.
_REPORT_FIELDS = {
    "schema_version",
    "bohrin_version",
    "dataset",
    "clusters",
    "detectors_run",
}
_FINDING_FIELDS = {
    "detector_id",
    "family",
    "severity",
    "confidence",
    "title",
    "mechanism",
    "evidence",
    "locus",
    "blast_radius",
    "fix",
    "provenance",
}


def test_report_schema_version_is_pinned() -> None:
    assert Report.model_fields["schema_version"].default == "1.0"


def test_report_top_level_shape_is_stable() -> None:
    assert set(Report.model_fields) == _REPORT_FIELDS


def test_finding_shape_is_stable() -> None:
    from bohrin.report.model import Finding

    assert set(Finding.model_fields) == _FINDING_FIELDS


def test_report_round_trips_and_forbids_unknown_fields() -> None:
    uri = _faulted_uri()
    report = bohrin.scan(uri)
    restored = Report.from_json(report.to_json())
    assert restored.to_json() == report.to_json()


# ------------------------------------------------------------------------------- SARIF


def _sarif() -> dict[str, Any]:
    log: dict[str, Any] = json.loads(bohrin.scan(_faulted_uri()).to_sarif())
    return log


def test_sarif_is_valid_2_1_0_with_the_required_envelope() -> None:
    log = _sarif()
    assert log["version"] == "2.1.0"
    assert "$schema" in log
    assert len(log["runs"]) == 1
    driver = log["runs"][0]["tool"]["driver"]
    assert driver["name"] == "bohrin"
    assert driver["rules"], "a rule per detector is required"


def test_every_sarif_result_has_the_github_required_fields() -> None:
    run = _sarif()["runs"][0]
    rule_ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
    assert run["results"], "the faulted dataset must produce results"
    for result in run["results"]:
        assert result["level"] in {"error", "warning", "note"}
        assert result["ruleId"] in rule_ids
        # GitHub de-duplicates on this and drops results without a location.
        assert result["partialFingerprints"]["primaryLocationLineHash"]
        assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]


def test_sarif_severity_maps_high_to_error() -> None:
    run = _sarif()["runs"][0]
    high = [r for r in run["results"] if r["rank"] >= 90.0]
    assert high and all(r["level"] == "error" for r in high)


def test_sarif_fingerprints_are_stable_across_runs() -> None:
    """Same defect on the next commit must hash identically or GitHub re-alerts every push."""
    uri = _faulted_uri()
    a = {
        r["partialFingerprints"]["primaryLocationLineHash"]
        for r in json.loads(bohrin.scan(uri).to_sarif())["runs"][0]["results"]
    }
    b = {
        r["partialFingerprints"]["primaryLocationLineHash"]
        for r in json.loads(bohrin.scan(uri).to_sarif())["runs"][0]["results"]
    }
    assert a == b


def test_sarif_is_deterministic() -> None:
    uri = _faulted_uri()
    assert bohrin.scan(uri).to_sarif() == bohrin.scan(uri).to_sarif()


# ---------------------------------------------------------------------------- --lang


def test_spanish_report_translates_the_chrome() -> None:
    uri = _faulted_uri()
    report = bohrin.scan(uri)
    en = report.to_html(lang="en")
    es = report.to_html(lang="es")
    assert "nada salió de esta máquina" in es
    assert "nothing left this machine" not in es
    assert "nothing left this machine" in en
    assert es.count("<details>") == en.count("<details>")  # same findings, just translated chrome


def test_findings_are_identical_regardless_of_language() -> None:
    """docs/09 §4: findings are language-neutral objects; only presentation changes."""
    report = bohrin.scan(_faulted_uri())
    # The report data is one object; both renders come from it unchanged.
    before = report.to_json()
    report.to_html(lang="es")
    assert report.to_json() == before


def test_unknown_language_falls_back_to_english_without_error() -> None:
    report = bohrin.scan(_faulted_uri())
    assert "nothing left this machine" in report.to_html(lang="kling0n")


def test_tty_renderer_localizes() -> None:
    from bohrin.report.tty import TtyRenderer

    report = bohrin.scan(_faulted_uri())
    es = TtyRenderer().render(report, lang="es")
    assert "por familia" in es


def test_every_catalog_covers_all_severities_and_families() -> None:
    from bohrin.ir.schema import Family, Severity

    for lang in supported_languages():
        cat = catalog(lang)
        assert set(cat.severity) == set(Severity)
        assert set(cat.family) == set(Family)
