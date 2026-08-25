"""The serializable output models: Finding, Cluster, Report (docs/03 §7, docs/06 P0).

These are pydantic models with a **versioned schema** (``Report.schema_version``). This is
L2's API surface: L2 diffs these JSON reports across dataset versions, so the shape is a
frozen contract (docs/09 §3). Everything here round-trips losslessly to/from JSON.

Symmetry with the IR: just as adapters normalize *input* into ``Episode``, detectors
normalize *output* into ``Finding`` — one type, whatever the check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from bohrin.ir.schema import Family, Provenance, Severity
from bohrin.version import REPORT_SCHEMA_VERSION, __version__


class _Frozen(BaseModel):
    """Base for immutable, strict output value objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Evidence(_Frozen):
    """The numbers backing a finding — what makes it falsifiable, not a vibe.

    ``series`` is the *picture* of the defect: the offending signal, downsampled to a
    bounded number of points so the JSON stays small and the HTML can draw a sparkline
    with no JavaScript (docs/05 §5). A flat line for a dead dimension is more convincing
    than the sentence "variance = 0", which is why the renderer shows it.
    """

    metrics: dict[str, float] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)
    notes: str = ""
    series: list[float] = Field(default_factory=list)
    series_label: str = ""


class Locus(_Frozen):
    """*Where* the defect is, so a user can open exactly that spot and see it."""

    episodes: list[str] = Field(default_factory=list)
    dimensions: list[int] = Field(default_factory=list)
    dimension_names: list[str] = Field(default_factory=list)
    step_window: tuple[int, int] | None = None
    camera: str | None = None


class BlastRadius(_Frozen):
    """How much of the dataset a finding touches — drives ranking."""

    n_episodes: int = 0
    total_episodes: int = 0
    frac_steps: float = 0.0

    @property
    def frac_episodes(self) -> float:
        """Fraction of episodes affected (0 if the dataset is empty)."""
        return self.n_episodes / self.total_episodes if self.total_episodes else 0.0


class Fix(_Frozen):
    """The concrete recommendation — human- and machine-readable."""

    text: str
    machine: dict[str, object] = Field(default_factory=dict)


class Finding(_Frozen):
    """One typed, falsifiable, actionable defect (docs/03 §7).

    ``mechanism`` is mandatory: a detector cannot emit HIGH without stating the causal
    story by which the defect degrades a learned policy (the honesty gate, principle 7).
    """

    detector_id: str
    family: Family
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    title: str
    mechanism: str
    evidence: Evidence = Field(default_factory=Evidence)
    locus: Locus = Field(default_factory=Locus)
    blast_radius: BlastRadius = Field(default_factory=BlastRadius)
    fix: Fix
    provenance: Provenance


class Cluster(_Frozen):
    """A group of findings that share a root cause → one headline (docs/02 §5)."""

    id: str
    title: str
    family: Family
    severity: Severity
    priority: float
    mechanism: str
    fix: Fix
    blast_radius: BlastRadius = Field(default_factory=BlastRadius)
    findings: list[Finding] = Field(default_factory=list)

    @property
    def detector_ids(self) -> list[str]:
        """The detector ids that contributed to this cluster."""
        return sorted({f.detector_id for f in self.findings})


class DatasetInfo(_Frozen):
    """The one-line dataset identity shown at the top of every report."""

    uri: str
    format: str
    n_episodes: int  # episodes actually scanned (after any triage sampling)
    total_episodes: int = 0  # episodes present in the dataset (== n_episodes when not sampled)
    total_steps: int = 0
    embodiment: str | None = None
    control_hz: float | None = None
    action_dim: int | None = None
    proprio_dim: int | None = None
    cameras: list[str] = Field(default_factory=list)

    @property
    def sampled(self) -> bool:
        """Whether this was a triage scan (fewer episodes analyzed than the dataset holds)."""
        return self.total_episodes > self.n_episodes


class Report(BaseModel):
    """The complete result of a scan — the frozen v1 contract (docs/06 P0 DoD).

    ``schema_version`` is independent of the package version and changes only when this
    serialized shape changes. The report never leaves the machine (docs/02 §6); there is
    no upload path in Layer 1.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = REPORT_SCHEMA_VERSION
    bohrin_version: str = __version__
    dataset: DatasetInfo
    #: There is deliberately **no aggregate score here.** A 0-100 number implies a
    #: calibration we do not have: nothing yet measures how much each defect actually costs
    #: a trained policy, so any weighting would be our guess dressed up as a measurement.
    #: Severity counts and the ranked clusters say everything we can currently defend.
    #: ``bohrin.synth.pipeline.quality_score`` still computes one, unreported, and the
    #: headline returns when a corpus of real training runs can back it.
    clusters: list[Cluster] = Field(default_factory=list)
    detectors_run: list[str] = Field(default_factory=list)
    # Deterministic by construction: no wall-clock timestamp is stored here, so two scans
    # of the same data produce byte-identical JSON (docs/02 §9). Display time lives in the
    # renderer, not the model.

    # ---- convenience accessors -------------------------------------------------------

    @property
    def counts(self) -> dict[Severity, int]:
        """Cluster counts by severity."""
        out: dict[Severity, int] = {s: 0 for s in Severity}
        for c in self.clusters:
            out[c.severity] += 1
        return out

    def family_counts(self) -> dict[Family, int]:
        """Cluster counts by family — the "where do my problems live" breakdown (docs/05 §5).

        Ordered by count descending so a renderer can show the dominant family first.
        """
        out: dict[Family, int] = {}
        for c in self.clusters:
            for f in {fi.family for fi in c.findings}:
                out[f] = out.get(f, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0].value)))

    def cluster(self, detector_id: str) -> Cluster | None:
        """The first cluster containing a finding from ``detector_id`` (or ``None``)."""
        for c in self.clusters:
            if detector_id in c.detector_ids:
                return c
        return None

    def max_severity(self) -> Severity | None:
        """The highest cluster severity present, or ``None`` if the report is clean."""
        if not self.clusters:
            return None
        return max((c.severity for c in self.clusters), key=lambda s: s.rank)

    # ---- serialization ---------------------------------------------------------------

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        """Serialize to JSON. Writes to ``path`` if given; always returns the string."""
        text = self.model_dump_json(indent=indent)
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    @classmethod
    def from_json(cls, data: str | bytes) -> Self:
        """Parse a report from JSON — the inverse of :meth:`to_json`."""
        return cls.model_validate_json(data)

    def to_html(self, path: str | Path | None = None, *, lang: str | None = None) -> str:
        """Render a self-contained HTML report. Writes to ``path`` if given; returns the string."""
        from bohrin.report.html import HtmlRenderer  # lazy: avoids a model→renderer import cycle

        html = HtmlRenderer().render(self, lang=lang)
        if path is not None:
            Path(path).write_text(html, encoding="utf-8")
        return html

    def to_sarif(self, path: str | Path | None = None) -> str:
        """Render a SARIF 2.1.0 log (GitHub code-scanning). Writes to ``path`` if given."""
        from bohrin.report.sarif import SarifRenderer  # lazy: avoids a model→renderer import cycle

        sarif = SarifRenderer().render(self)
        if path is not None:
            Path(path).write_text(sarif, encoding="utf-8")
        return sarif
