"""Localization catalogs for the report chrome (docs/05 §3,§7, docs/09 §4).

`--lang` localizes the report. The design rule from `09 §4` is that **findings are
language-neutral objects**: a `Finding` carries structured data (a detector id, a severity,
numbers, a locus), and the *presentation* is what gets translated. So a scan produces the
exact same `Report` regardless of `--lang` — only the renderer's fixed vocabulary changes:
the section labels, severity names, "Why it hurts" / "Fix" / "Where".

**Honest scope.** This catalog translates the report *chrome*. A finding's own generated
sentences (title, mechanism, fix) are still authored in English by each detector, because
translating them faithfully needs the detectors to emit message *keys* with interpolated
parameters rather than finished prose — a larger change tracked as future work. What ships
here is real and complete for what it covers: a Spanish report reads as Spanish everywhere
the tool speaks in its own voice.

Adding a language is one dict. Unknown languages fall back to English, never error.
"""

from __future__ import annotations

from dataclasses import dataclass

from bohrin.ir.schema import Family, Severity


@dataclass(frozen=True, slots=True)
class Catalog:
    """The translated chrome for one language. Every field is a fixed UI string."""

    lang: str
    no_findings: str
    clean: str
    by_family: str
    why_it_hurts: str
    evidence: str
    where: str
    fix: str
    provenance: str
    next_hint: str
    more_findings: str
    nothing_blocking: str
    things_to_fix: str
    footer_local: str
    severity: dict[Severity, str]
    family: dict[Family, str]


_SEV_EN = {
    Severity.HIGH: "HIGH",
    Severity.MEDIUM: "MEDIUM",
    Severity.LOW: "LOW",
    Severity.INFO: "INFO",
}
_FAM_EN = {f: f.value.lower() for f in Family}

_EN = Catalog(
    lang="en",
    no_findings="No findings. The data looks clean.",
    clean="clean",
    by_family="by family",
    why_it_hurts="Why it hurts",
    evidence="Evidence",
    where="Where",
    fix="Fix",
    provenance="Provenance",
    next_hint="Next",
    more_findings="more finding(s)",
    nothing_blocking="Nothing blocking. The findings below are quality improvements, not reasons to hold off training.",
    things_to_fix="The things to fix before you train",
    footer_local="Findings computed locally; nothing left this machine.",
    severity=_SEV_EN,
    family=_FAM_EN,
)

_ES = Catalog(
    lang="es",
    no_findings="Sin hallazgos. Los datos parecen limpios.",
    clean="limpio",
    by_family="por familia",
    why_it_hurts="Por qué perjudica",
    evidence="Evidencia",
    where="Dónde",
    fix="Solución",
    provenance="Procedencia",
    next_hint="Siguiente",
    more_findings="hallazgo(s) más",
    nothing_blocking=(
        "Nada que bloquee. Los hallazgos siguientes son mejoras de calidad, no motivos para posponer el entrenamiento."
    ),
    things_to_fix="Lo que debes corregir antes de entrenar",
    footer_local="Hallazgos calculados localmente; nada salió de esta máquina.",
    severity={
        Severity.HIGH: "ALTO",
        Severity.MEDIUM: "MEDIO",
        Severity.LOW: "BAJO",
        Severity.INFO: "INFO",
    },
    family={
        Family.INTEGRITY: "integridad",
        Family.STATS: "estadísticas",
        Family.SMOOTHNESS: "suavidad",
        Family.TEMPORAL: "temporal",
        Family.COVERAGE: "cobertura",
        Family.DYNAMICS: "dinámica",
        Family.CONSISTENCY: "consistencia",
        Family.MULTIMODALITY: "multimodalidad",
        Family.VISION: "visión",
        Family.LABEL: "etiquetas",
        Family.CAUSAL: "causal",
        Family.POLICY_DATA: "política-datos",
    },
)

_CATALOGS: dict[str, Catalog] = {c.lang: c for c in (_EN, _ES)}


def catalog(lang: str | None) -> Catalog:
    """The catalog for ``lang``, falling back to English for an unknown code.

    Never raises: a report must render in *some* language even if the requested one has no
    catalog yet. The CLI separately warns when it falls back, so the user knows.
    """
    if not lang:
        return _EN
    return _CATALOGS.get(lang.lower(), _EN)


def is_supported(lang: str) -> bool:
    """Whether a full catalog exists for ``lang`` (drives the CLI's fallback notice)."""
    return lang.lower() in _CATALOGS


def supported_languages() -> tuple[str, ...]:
    return tuple(sorted(_CATALOGS))
