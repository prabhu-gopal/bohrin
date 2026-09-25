"""Probe manifests: every built-in probe, described as data.

A probe exists as code (the operator that generates its submissions) and as a manifest that a
third-party tool or the conformance suite can read without importing Bohrin. The manifests ship
in the package as ``probes.toml`` and are checked on load, against the identifier formats and
the weakness list.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any

from bohrin.ir.task import Ground, Shape, Workspace
from bohrin.spec.ids import is_probe_id
from bohrin.spec.weaknesses import WeaknessList, weakness_list

#: What a correct grader does with a probe's submission.
EXPECT: Mapping[str, str] = MappingProxyType(
    {
        "reject": "a negative control: the submission is wrong, and a correct grader rejects it",
        "accept": "a positive control: the submission is correct, and a correct grader accepts it",
        "consistent": "a repeat: a correct grader gives the same verdict every time",
    }
)

#: The solution half of a probe's template.
SOLUTIONS: Mapping[str, str] = MappingProxyType(
    {
        "no-op": "the task is not attempted",
        "reference": "the declared solution, unchanged",
        "reference-emptied": "the declared solution with every function body replaced by pass",
        "reference-constant": "the declared solution with every function returning a constant of its return type",
        "reference-raising": "the declared solution with every function body replaced by raise NotImplementedError",
        "reference-exiting": "the declared solution with every function body replaced by sys.exit(0)",
        "reference-spoofed": "the declared solution with every function returning a spoofed object",
        "reference-rewritten": "the declared solution rewritten in a way certified not to change what it does",
    }
)

MATURITIES = ("experimental", "stable", "deprecated")


@dataclass(frozen=True, slots=True)
class Template:
    """What a probe submits, independent of any particular environment."""

    #: A key of :data:`SOLUTIONS`.
    solution: str
    #: Path -> the name of the file written there. Paths may name ``parameters``.
    files: Mapping[str, str]
    #: What an instantiation must supply. Never filled in by this library.
    parameters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Probe:
    """One probe's manifest."""

    id: str
    #: The entry-point name of the operator that generates it.
    operator: str
    weakness: tuple[str, ...]
    title: str
    shapes: tuple[Shape, ...]
    #: The ground a negative control rests on; None for a positive control or a repeat.
    ground: Ground | None
    expect: str
    maturity: str
    battery: int
    template: Template
    #: Conditions under which the probe submits nothing, or submits only a lead.
    guards: tuple[str, ...]
    sources: tuple[str, ...]


def _strings(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{where}: expected a list of strings")
    return tuple(value)


def _text(entry: Mapping[str, Any], key: str, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: {key!r} must be a non-empty string")
    return value


def _template(raw: Any, where: str) -> Template:
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: needs a [template] table")
    solution = _text(raw, "solution", f"{where}.template")
    if solution not in SOLUTIONS:
        raise ValueError(f"{where}: solution must be one of {sorted(SOLUTIONS)}")
    parameters = _strings(raw.get("parameters", []), f"{where}.template.parameters")
    raw_files = raw.get("files", {})
    if not isinstance(raw_files, dict) or not all(isinstance(v, str) for v in raw_files.values()):
        raise ValueError(f"{where}: template.files maps paths to template names")
    try:
        # The same rules a submitted workspace is held to: relative paths inside the root, and
        # every parameter a path names is declared.
        Workspace(dict.fromkeys(raw_files, ""), parameters=parameters)
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    return Template(solution=solution, files=MappingProxyType(dict(raw_files)), parameters=parameters)


def _probe(entry: Mapping[str, Any], weaknesses: WeaknessList) -> Probe:
    probe_id = entry.get("id")
    if not isinstance(probe_id, str) or not is_probe_id(probe_id):
        raise ValueError(f"malformed probe ID: {probe_id!r}")
    where = probe_id
    weakness = _strings(entry.get("weakness"), f"{where}.weakness")
    known = {w.id for w in weaknesses.weaknesses}
    if not weakness or set(weakness) - known:
        raise ValueError(f"{where}: weakness must name one or more classes in the weakness list")
    try:
        shapes = tuple(Shape(s) for s in _strings(entry.get("shapes"), f"{where}.shapes"))
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}") from exc
    if not shapes:
        raise ValueError(f"{where}: names no grader shape")
    expect = _text(entry, "expect", where)
    if expect not in EXPECT:
        raise ValueError(f"{where}: expect must be one of {sorted(EXPECT)}")
    raw_ground = entry.get("ground")
    if expect == "reject":
        # A negative control with no ground would be an accusation with nothing behind it.
        if not isinstance(raw_ground, str):
            raise ValueError(f"{where}: a negative control must name its ground")
        try:
            ground: Ground | None = Ground(raw_ground)
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from exc
    elif raw_ground is not None:
        raise ValueError(f"{where}: only a negative control carries a ground")
    else:
        ground = None
    maturity = _text(entry, "maturity", where)
    if maturity not in MATURITIES:
        raise ValueError(f"{where}: maturity must be one of {MATURITIES}")
    battery = entry.get("battery")
    if not isinstance(battery, int) or battery < 1:
        raise ValueError(f"{where}: battery must be a positive integer")
    sources = _strings(entry.get("sources"), f"{where}.sources")
    if not sources or not all(s.startswith("https://") for s in sources):
        raise ValueError(f"{where}: needs at least one public https source")
    return Probe(
        id=probe_id,
        operator=_text(entry, "operator", where),
        weakness=weakness,
        title=_text(entry, "title", where),
        shapes=shapes,
        ground=ground,
        expect=expect,
        maturity=maturity,
        battery=battery,
        template=_template(entry.get("template"), where),
        guards=_strings(entry.get("guards", []), f"{where}.guards"),
        sources=sources,
    )


def parse(text: str, weaknesses: WeaknessList | None = None) -> tuple[Probe, ...]:
    """Parse and check probe manifests. Raises ``ValueError`` on anything malformed."""
    wl = weaknesses if weaknesses is not None else weakness_list()
    probes = [_probe(entry, wl) for entry in tomllib.loads(text).get("probe", [])]
    for key in ("id", "operator"):
        values = [getattr(p, key) for p in probes]
        repeated = sorted({v for v in values if values.count(v) > 1})
        if repeated:
            raise ValueError(f"duplicate probe {key}s: {repeated}")
    return tuple(sorted(probes, key=lambda p: p.id))


@cache
def probes() -> tuple[Probe, ...]:
    """The manifests of every built-in probe."""
    return parse(files("bohrin.spec").joinpath("probes.toml").read_text(encoding="utf-8"))


def probe_for(operator: str) -> Probe | None:
    """The built-in manifest for an operator, or None for an operator that has none."""
    return next((p for p in probes() if p.operator == operator), None)


__all__ = ["EXPECT", "MATURITIES", "SOLUTIONS", "Probe", "Template", "parse", "probe_for", "probes"]
