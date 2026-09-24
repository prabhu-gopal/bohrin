"""The weakness list: every published way a coding grader or its harness can be cheated or be wrong.

Each class has a permanent ``BGW-`` ID that probes, findings, registry records and fix guidance
refer to, the way a CVE refers to a CWE. The list is data (``weaknesses.toml``, shipped in the
package) so that any tool can read it without importing Bohrin, and it is checked on load: a
malformed list raises instead of quietly publishing a broken identifier.

``docs/WEAKNESSES.md`` is generated from it::

    python -m bohrin.spec > docs/WEAKNESSES.md
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any

from bohrin.ir.task import Ground, Shape
from bohrin.spec.ids import is_weakness_id, weakness_number

#: The kinds of evidence a finding of a class can carry, and what each one is.
EVIDENCE: Mapping[str, str] = MappingProxyType(
    {
        "reproduction": "a submission the grader paid for, re-created by a standalone reproduction script",
        "differentiating-input": "an input on which the submission and the reference produce different outputs",
        "differentiating-observation": (
            "a read-only check of the end state, tied to a sentence of the task, that the reference and "
            "presumed-correct solutions pass and the submission fails"
        ),
        "fact": "a fact read from version history, such as a deleted test or an added exit call",
        "statistic": "a measurement over many tasks or runs, reported with its interval",
        "positive-control": "a certified-correct submission the grader rejected",
        "structural-risk": "a risk read from the harness without a working exploit, reported as suspected",
    }
)

#: What this library provides for a class, beyond its definition.
PROVIDES: Mapping[str, str] = MappingProxyType(
    {
        "template": "a template that generates the attack or the control",
        "fact": "a fact rule read from version history",
        "statistic": "a statistic in the scoring",
    }
)

STATUSES = ("active", "deprecated")


@dataclass(frozen=True, slots=True)
class Weakness:
    """One weakness class."""

    id: str
    name: str
    family: str
    #: Why the defect matters: how a grader with it pays for the wrong thing.
    mechanism: str
    shapes: tuple[Shape, ...]
    #: The grounds a proven finding of this class can rest on. Empty when its evidence is a
    #: statistic, a positive control or a structural risk, none of which is a wrong submission.
    grounds: tuple[Ground, ...]
    evidence: tuple[str, ...]
    #: Keys of :data:`PROVIDES`. Empty means the class is defined here and nothing more.
    provides: tuple[str, ...]
    #: Static guidance on closing the weakness, true of any grader that has it.
    fix: str
    sources: tuple[str, ...]
    status: str = "active"

    @property
    def number(self) -> int:
        """The ID's number, for ordering: ``BGW-108`` is ``108``. It carries no other meaning."""
        return weakness_number(self.id)


@dataclass(frozen=True, slots=True)
class Crosswalk:
    """Another published taxonomy's categories, mapped to weakness IDs."""

    key: str
    title: str
    source: str
    #: Category -> weakness IDs. An empty tuple means the category is not a grader weakness.
    map: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class WeaknessList:
    """The whole list, in ID order."""

    version: int
    families: Mapping[str, str]
    weaknesses: tuple[Weakness, ...]
    crosswalks: tuple[Crosswalk, ...]

    def get(self, weakness_id: str) -> Weakness:
        """The class with this ID. Raises ``KeyError`` for an unknown one."""
        for weakness in self.weaknesses:
            if weakness.id == weakness_id:
                return weakness
        raise KeyError(weakness_id)

    def in_family(self, family: str) -> tuple[Weakness, ...]:
        """The classes in one family, in ID order."""
        return tuple(w for w in self.weaknesses if w.family == family)


def _strings(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{where}: expected a list of strings")
    return tuple(value)


def _text(entry: Mapping[str, Any], key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: {key!r} must be a non-empty string")
    return value


def _weakness(entry: Mapping[str, Any], families: Mapping[str, str]) -> Weakness:
    weakness_id = entry.get("id")
    if not isinstance(weakness_id, str) or not is_weakness_id(weakness_id):
        raise ValueError(f"malformed weakness ID: {weakness_id!r}")
    where = weakness_id
    family = _text(entry, "family", where)
    if family not in families:
        raise ValueError(f"{where}: unknown family {family!r}")
    try:
        shapes = tuple(Shape(s) for s in _strings(entry.get("shapes"), f"{where}.shapes"))
        grounds = tuple(Ground(g) for g in _strings(entry.get("grounds"), f"{where}.grounds"))
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    evidence = _strings(entry.get("evidence"), f"{where}.evidence")
    provides = _strings(entry.get("provides"), f"{where}.provides")
    sources = _strings(entry.get("sources"), f"{where}.sources")
    status = entry.get("status", "active")
    if not shapes:
        raise ValueError(f"{where}: names no grader shape")
    if not evidence or set(evidence) - set(EVIDENCE):
        raise ValueError(f"{where}: evidence must be one or more of {sorted(EVIDENCE)}")
    if set(provides) - set(PROVIDES):
        raise ValueError(f"{where}: provides must be drawn from {sorted(PROVIDES)}")
    if not sources or not all(s.startswith("https://") for s in sources):
        raise ValueError(f"{where}: needs at least one public https source")
    if status not in STATUSES:
        raise ValueError(f"{where}: status must be one of {STATUSES}")
    return Weakness(
        id=weakness_id,
        name=_text(entry, "name", where),
        family=family,
        mechanism=_text(entry, "mechanism", where),
        shapes=shapes,
        grounds=grounds,
        evidence=evidence,
        provides=provides,
        fix=_text(entry, "fix", where),
        sources=sources,
        status=status,
    )


def parse(text: str) -> WeaknessList:
    """Parse and check a weakness list. Raises ``ValueError`` on anything malformed."""
    data = tomllib.loads(text)
    version = data.get("version")
    if not isinstance(version, int) or version < 1:
        raise ValueError("the list needs an integer version of at least 1")
    raw_families = data.get("families")
    if not isinstance(raw_families, dict) or not raw_families:
        raise ValueError("the list needs a [families] table")
    families = MappingProxyType({str(k): str(v) for k, v in raw_families.items()})

    weaknesses = [_weakness(entry, families) for entry in data.get("weakness", [])]
    ids = [w.id for w in weaknesses]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate weakness IDs: {duplicates}")
    weaknesses.sort(key=lambda w: w.number)

    crosswalks: list[Crosswalk] = []
    for key, table in (data.get("crosswalk") or {}).items():
        where = f"crosswalk {key!r}"
        mapping: dict[str, tuple[str, ...]] = {}
        for category, targets in (table.get("map") or {}).items():
            mapped = _strings(targets, f"{where}.{category}")
            unknown = sorted(set(mapped) - set(ids))
            if unknown:
                raise ValueError(f"{where}: {category!r} maps to unknown IDs {unknown}")
            mapping[category] = mapped
        if not mapping:
            raise ValueError(f"{where}: maps no categories")
        source = _text(table, "source", where)
        crosswalks.append(
            Crosswalk(key=key, title=_text(table, "title", where), source=source, map=MappingProxyType(mapping))
        )

    return WeaknessList(version=version, families=families, weaknesses=tuple(weaknesses), crosswalks=tuple(crosswalks))


@cache
def weakness_list() -> WeaknessList:
    """The weakness list shipped with this package."""
    return parse(files("bohrin.spec").joinpath("weaknesses.toml").read_text(encoding="utf-8"))


def render_markdown(weaknesses: WeaknessList | None = None) -> str:
    """The list as the Markdown page published at ``docs/WEAKNESSES.md``."""
    wl = weaknesses if weaknesses is not None else weakness_list()
    out = [
        "# Weakness list",
        "",
        "<!-- Generated from src/bohrin/spec/weaknesses.toml by `python -m bohrin.spec > docs/WEAKNESSES.md`. "
        "Do not edit by hand. -->",
        "",
        f"Version **{wl.version}**. Every published way a coding grader or its harness can be cheated "
        "or be wrong, each with a permanent ID. Probes, findings, registry records and fix guidance "
        "refer to these IDs. The number in an ID carries no meaning and is never reused; families "
        "are for reading the list and are not part of the ID.",
        "",
        "Each class names the grader shapes it applies to, the evidence a finding of it carries, and "
        "what this library provides for it beyond the definition:",
        "",
        *(f"- **{key}**: {text}" for key, text in PROVIDES.items()),
        "",
        "Evidence kinds:",
        "",
        *(f"- **{key}**: {text}" for key, text in EVIDENCE.items()),
        "",
    ]
    for family, title in wl.families.items():
        members = wl.in_family(family)
        if not members:
            continue
        out += [f"## {title}", "", "| ID | Weakness | Shapes | Provides |", "|---|---|---|---|"]
        for w in members:
            provides = ", ".join(w.provides) or "definition"
            shapes = ", ".join(s.value for s in w.shapes)
            out.append(f"| [{w.id}](#{w.id.lower()}) | {w.name} | {shapes} | {provides} |")
        out.append("")
        for w in members:
            status = " (deprecated)" if w.status == "deprecated" else ""
            out += [
                f"### {w.id}",
                "",
                f"**{w.name}**{status}. {w.mechanism}",
                "",
                f"- **Evidence:** {', '.join(w.evidence)}",
                f"- **Grounds:** {', '.join(g.value for g in w.grounds) or 'none'}",
                f"- **Fix:** {w.fix}",
                f"- **Sources:** {' · '.join(f'<{s}>' for s in w.sources)}",
                "",
            ]
    out += [
        "## Crosswalks",
        "",
        "Categories from other published taxonomies, mapped to the classes above, so a reader who "
        "knows one vocabulary can read this one.",
        "",
    ]
    for cw in wl.crosswalks:
        out += [f"### {cw.title}", "", f"Source: <{cw.source}>", "", "| Category | Classes |", "|---|---|"]
        for category, targets in cw.map.items():
            out.append(f"| {category} | {', '.join(targets) or 'none (not a grader weakness)'} |")
        out.append("")
    return "\n".join(out)


__all__ = [
    "EVIDENCE",
    "PROVIDES",
    "STATUSES",
    "Crosswalk",
    "Weakness",
    "WeaknessList",
    "parse",
    "render_markdown",
    "weakness_list",
]
