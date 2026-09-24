"""Probe manifests: each built-in operator emits exactly what its manifest promises.

A manifest is a public claim about what a probe tries. If the code drifted from it, a reader
checking a finding against the manifest would be checking the wrong thing, so the two are tied
together here from both sides, and the loader's rules are each exercised by a manifest that
breaks exactly one of them.
"""

from __future__ import annotations

import pytest

from _fixtures import REFERENCE, task
from bohrin.mutate import discover
from bohrin.scoring.coverage import BATTERY_VERSION
from bohrin.spec.probes import parse, probe_for, probes
from bohrin.spec.weaknesses import weakness_list

# --------------------------------------------------------------------------- code and data agree


def test_every_built_in_operator_has_exactly_one_manifest_and_back() -> None:
    assert {op.id for op in discover()} == {p.operator for p in probes()}


def test_built_in_probes_are_in_the_bohrin_namespace_and_the_current_battery() -> None:
    for probe in probes():
        assert probe.id.startswith("bohrin/"), probe.id
        assert str(probe.battery) == BATTERY_VERSION, probe.id


@pytest.mark.parametrize("operator", [op.id for op in discover()])
def test_an_operator_emits_what_its_manifest_promises(operator: str) -> None:
    op = next(o for o in discover() if o.id == operator)
    probe = probe_for(operator)
    assert probe is not None

    assert set(op.shapes) == set(probe.shapes), "the operator runs on exactly the manifest's shapes"
    candidates = list(op.apply(task(REFERENCE)))
    assert candidates, "the fixture should give the operator something to emit"
    assert {c.ground for c in candidates} == {probe.ground}, "every submission carries the manifest's ground"


@pytest.mark.parametrize("probe_id", [p.id for p in probes()])
def test_an_operator_counts_towards_the_family_of_its_weakness(probe_id: str) -> None:
    probe = next(p for p in probes() if p.id == probe_id)
    op = next(o for o in discover() if o.id == probe.operator)
    assert op.category == weakness_list().get(probe.weakness[0]).family


def test_every_probe_is_experimental_until_its_error_rate_is_measured() -> None:
    """Stable needs a public sample with a measured precision; none has been published."""
    assert {p.maturity for p in probes()} == {"experimental"}


# --------------------------------------------------------------------------- the loader's checks

_GOOD = """
[[probe]]
id = "acme/reward-write@1"
operator = "reward_write"
weakness = ["BGW-111"]
title = "Write the maximum reward"
shapes = ["container"]
ground = "structural"
expect = "reject"
maturity = "experimental"
battery = 2
sources = ["https://example.org/paper"]
[probe.template]
solution = "no-op"
parameters = ["reward_path"]
[probe.template.files]
"{reward_path}" = "reward_max.txt"
"""


def test_a_third_party_manifest_with_a_parameterised_template_parses() -> None:
    (probe,) = parse(_GOOD)
    assert probe.template.parameters == ("reward_path",)
    assert dict(probe.template.files) == {"{reward_path}": "reward_max.txt"}


@pytest.mark.parametrize(
    ("breakage", "old", "new"),
    [
        ("malformed ID", 'id = "acme/reward-write@1"', 'id = "reward-write"'),
        ("unknown weakness", 'weakness = ["BGW-111"]', 'weakness = ["BGW-999"]'),
        ("no weakness", 'weakness = ["BGW-111"]', "weakness = []"),
        ("unknown shape", 'shapes = ["container"]', 'shapes = ["spreadsheet"]'),
        ("unknown ground", 'ground = "structural"', 'ground = "vibes"'),
        ("positive control with a ground", 'expect = "reject"', 'expect = "accept"'),
        ("unknown expectation", 'expect = "reject"', 'expect = "maybe"'),
        ("unknown maturity", 'maturity = "experimental"', 'maturity = "beta"'),
        ("no battery", "battery = 2", "battery = 0"),
        ("no source", 'sources = ["https://example.org/paper"]', "sources = []"),
        ("unknown solution", 'solution = "no-op"', 'solution = "magic"'),
        ("undeclared parameter", 'parameters = ["reward_path"]', "parameters = []"),
        ("path leaves the root", '"{reward_path}" = ', '"../{reward_path}" = '),
    ],
)
def test_a_manifest_breaking_one_rule_is_refused(breakage: str, old: str, new: str) -> None:
    assert old in _GOOD, breakage
    with pytest.raises(ValueError):
        parse(_GOOD.replace(old, new, 1))


def test_a_negative_control_must_name_its_ground() -> None:
    """A negative control with no ground would be an accusation with nothing behind it."""
    with pytest.raises(ValueError, match="must name its ground"):
        parse(_GOOD.replace('ground = "structural"\n', "", 1))


def test_a_repeated_probe_id_is_refused() -> None:
    second = _GOOD.replace('operator = "reward_write"', 'operator = "other"')
    with pytest.raises(ValueError, match="duplicate"):
        parse(_GOOD + second)
