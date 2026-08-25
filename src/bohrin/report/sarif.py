"""The SARIF renderer — Stage ⑥, GitHub code-scanning native output (docs/05 §3, docs/09 §4).

SARIF (Static Analysis Results Interchange Format, OASIS 2.1.0) is the format GitHub code
scanning, VS Code and most IDEs read. Emitting it means a data defect shows up on a pull
request exactly like a code defect — an inline annotation the team already knows how to
triage. That is the whole point: it drops Layer 1 into the review workflow with zero new UI.

The mapping is grounded in what GitHub actually consumes (verified against its SARIF-support
docs), not the full 2.1.0 surface:

* ``result.level`` ∈ {``error``, ``warning``, ``note``} — HIGH→error, MEDIUM→warning, the
  rest→note. There is no "critical", so severity beyond that rides in ``rank``.
* ``partialFingerprints.primaryLocationLineHash`` is **required** for stable de-duplication
  across runs; without it GitHub re-alerts on every push. We derive it from the detector id
  and locus, which are exactly the identity of a finding.
* Every result needs **at least one physical location** or GitHub drops it. Our findings are
  about a *dataset*, not a source line, so we anchor them to the dataset artifact and carry
  the true locus (episode, dimension, camera) in ``logicalLocations`` and ``message``.
* One ``reportingDescriptor`` (rule) per detector, with ``helpUri`` deep-linking to
  ``bohrin explain`` and ``fullDescription`` from the detector's own docstring.

Like every renderer this is a pure sink over the frozen :class:`Report`; it never mutates it
and adds no dependency (SARIF is just JSON).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from bohrin.ir.schema import Severity
from bohrin.report.model import Cluster, Finding, Report
from bohrin.version import __version__

_SARIF_VERSION = "2.1.0"
_SCHEMA_URI = "https://json.schemastore.org/sarif-2.1.0.json"
_HELP_BASE = "https://bohrin.com/docs/detectors"

#: Severity → SARIF result level. SARIF has only three levels, so HIGH and any future
#: "critical" both map to ``error``; the finer ranking survives in ``rank`` below.
_LEVEL: dict[Severity, str] = {
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "note",
    Severity.INFO: "note",
}

#: Severity → a 0–100 ``rank`` so GitHub orders our results the way our own report does.
#: (GitHub sorts by rank when several results share a level.)
_RANK: dict[Severity, float] = {
    Severity.HIGH: 90.0,
    Severity.MEDIUM: 60.0,
    Severity.LOW: 30.0,
    Severity.INFO: 10.0,
}


class SarifRenderer:
    """Renders a :class:`Report` to a SARIF 2.1.0 log string. A :class:`Renderer`."""

    def render(self, report: Report) -> str:
        rules, rule_index = self._rules(report)
        results = [self._result(c, f, rule_index) for c in report.clusters for f in c.findings]
        log: dict[str, Any] = {
            "$schema": _SCHEMA_URI,
            "version": _SARIF_VERSION,
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "bohrin",
                            "informationUri": "https://bohrin.com",
                            "version": __version__,
                            "rules": rules,
                        }
                    },
                    # The dataset is the artifact under analysis — the SARIF equivalent of a
                    # source file. Findings' physicalLocations reference it by index 0.
                    "artifacts": [{"location": {"uri": _artifact_uri(report)}, "description": {"text": "dataset"}}],
                    "results": results,
                    # Deterministic by construction: no timestamps, sorted rules, stable
                    # fingerprints — two scans of the same data give byte-identical SARIF.
                    "columnKind": "utf16CodeUnits",
                }
            ],
        }
        return json.dumps(log, indent=2, ensure_ascii=False, sort_keys=False)

    def _rules(self, report: Report) -> tuple[list[dict[str, Any]], dict[str, int]]:
        """One reportingDescriptor per detector that produced a finding, sorted by id."""
        seen: dict[str, Cluster] = {}
        for cluster in report.clusters:
            for finding in cluster.findings:
                seen.setdefault(finding.detector_id, cluster)
        rules: list[dict[str, Any]] = []
        index: dict[str, int] = {}
        for i, detector_id in enumerate(sorted(seen)):
            cluster = seen[detector_id]
            index[detector_id] = i
            rules.append(
                {
                    "id": detector_id,
                    "name": _camel(detector_id),
                    "shortDescription": {"text": cluster.title},
                    "fullDescription": {"text": cluster.mechanism},
                    "helpUri": f"{_HELP_BASE}#{detector_id}",
                    "help": {"text": f"Run `bohrin explain {detector_id}` for the mechanism and an example."},
                    "defaultConfiguration": {"level": _LEVEL[cluster.severity]},
                    "properties": {"family": cluster.family.value},
                }
            )
        return rules, index

    def _result(self, cluster: Cluster, finding: Finding, rule_index: dict[str, int]) -> dict[str, Any]:
        message = self._message(cluster, finding)
        result: dict[str, Any] = {
            "ruleId": finding.detector_id,
            "ruleIndex": rule_index[finding.detector_id],
            "level": _LEVEL[finding.severity],
            "rank": _RANK[finding.severity],
            "message": {"text": message},
            "locations": [self._location(finding)],
            # Required by GitHub for cross-run de-duplication. The identity of a finding is
            # (detector, where it fired) — hashing that keeps a persistent defect from
            # re-alerting on every push while a genuinely new one still surfaces.
            "partialFingerprints": {"primaryLocationLineHash": _fingerprint(finding)},
            "properties": {
                "confidence": round(finding.confidence, 4),
                "family": finding.family.value,
                "n_episodes": finding.blast_radius.n_episodes,
                "fix": finding.fix.text,
            },
        }
        return result

    def _location(self, finding: Finding) -> dict[str, Any]:
        """A physical location on the dataset artifact, plus the true locus as logical.

        GitHub requires a physical location to render a result at all, but our defect is not
        at a source line — it is at an episode/dimension. So the physical location points at
        the dataset (region line 1, a stable anchor) and the *real* address lives in
        ``logicalLocations`` and the message, where it is both correct and human-readable.
        """
        location: dict[str, Any] = {
            "physicalLocation": {
                "artifactLocation": {"uri": _location_uri(finding), "index": 0},
                "region": {"startLine": 1},
            }
        }
        logical = _logical_locations(finding)
        if logical:
            location["logicalLocations"] = logical
        return location

    def _message(self, cluster: Cluster, finding: Finding) -> str:
        parts = [finding.title, finding.mechanism]
        where = _where(finding)
        if where:
            parts.append(f"Where: {where}.")
        parts.append(f"Fix: {finding.fix.text}")
        return " ".join(p for p in parts if p)


# ------------------------------------------------------------------------------ helpers


def _artifact_uri(report: Report) -> str:
    return _relativize(report.dataset.uri)


def _location_uri(finding: Finding) -> str:
    return _relativize(finding.provenance.uri)


def _relativize(uri: str) -> str:
    """A repo-relative, forward-slash URI. GitHub matches these against the checkout."""
    text = uri.replace("\\", "/")
    return text[2:] if text.startswith("./") else text


def _logical_locations(finding: Finding) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for episode in finding.locus.episodes[:16]:
        out.append({"name": episode, "kind": "episode"})
    for i, dim in enumerate(finding.locus.dimensions):
        name = finding.locus.dimension_names[i] if i < len(finding.locus.dimension_names) else str(dim)
        out.append({"name": name, "fullyQualifiedName": f"dim[{dim}]", "kind": "dimension"})
    if finding.locus.camera:
        out.append({"name": finding.locus.camera, "kind": "camera"})
    return out


def _where(finding: Finding) -> str:
    loc = finding.locus
    bits: list[str] = []
    if loc.dimension_names:
        bits.append("dims " + ", ".join(loc.dimension_names))
    elif loc.dimensions:
        bits.append("dims " + ", ".join(str(d) for d in loc.dimensions))
    if loc.camera:
        bits.append(f"camera {loc.camera}")
    if loc.episodes:
        shown = ", ".join(loc.episodes[:6])
        extra = f" +{len(loc.episodes) - 6} more" if len(loc.episodes) > 6 else ""
        bits.append(f"episodes {shown}{extra}")
    return " · ".join(bits)


def _fingerprint(finding: Finding) -> str:
    """A stable hash of a finding's *identity* (detector + locus), not its numbers.

    Deliberately excludes metric values: the same dead dimension found on the next commit
    must hash identically so GitHub treats it as the same alert, even though the exact
    variance differs run to run. Only a change in *what* or *where* is a new finding.
    """
    loc = finding.locus
    identity = "|".join(
        [
            finding.detector_id,
            ",".join(sorted(loc.episodes)),
            ",".join(str(d) for d in sorted(loc.dimensions)),
            loc.camera or "",
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _camel(detector_id: str) -> str:
    """``stats.dead_dimension`` → ``StatsDeadDimension`` for SARIF's ``rule.name``."""
    return "".join(part.capitalize() for part in detector_id.replace(".", "_").split("_"))
