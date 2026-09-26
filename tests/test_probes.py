"""Probe manifests: each built-in operator emits exactly what its manifest promises.

A manifest is a public claim about what a probe tries. If the code drifted from it, a reader
checking a finding against the manifest would be checking the wrong thing, so the two are tied
together here from both sides, and the loader's rules are each exercised by a manifest that
breaks exactly one of them.
"""

from __future__ import annotations

import pytest

from _fixtures import REFERENCE, task
from bohrin.ir.task import Source, Workspace
from bohrin.mutate import discover
from bohrin.mutate.base import MutationOperator
from bohrin.relations import BASELINE
from bohrin.relations import discover as discover_relations
from bohrin.scoring.coverage import BATTERY_VERSION
from bohrin.spec.probes import parse, probe_for, probes, weakness_of
from bohrin.spec.weaknesses import weakness_list

# --------------------------------------------------------------------------- code and data agree


def test_every_built_in_generator_has_exactly_one_manifest_and_back() -> None:
    """Operators (negative controls) and relations plus the baseline (positive controls)."""
    generators = {op.id for op in discover()} | {r.id for r in discover_relations()} | {BASELINE}
    assert generators == {p.operator for p in probes()}


def test_negative_controls_reject_and_positive_controls_accept() -> None:
    for probe in probes():
        operator = probe.operator in {op.id for op in discover()}
        assert probe.expect == ("reject" if operator else "accept"), probe.id


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
    for c in candidates:
        if isinstance(c.payload, Workspace):
            assert set(c.payload.files) == set(probe.template.files), "the manifest names every file written"
            assert c.payload.parameters == probe.template.parameters, "and every parameter to fill in"
        else:
            assert isinstance(c.payload, Source)
            assert not probe.template.files and not probe.template.parameters, "a program needs no instantiation"


def test_a_workspace_writes_the_solution_its_manifest_names() -> None:
    """The empty implementation is the only solution a workspace probe writes; it is where its ground is."""
    (emptied,) = discover_one("drop_side_effect").apply(task(REFERENCE))
    for probe in probes():
        if "{source_path}" in probe.template.files:
            assert probe.template.solution == "reference-emptied", probe.id
            (candidate,) = discover_one(probe.operator).apply(task(REFERENCE))
            assert isinstance(candidate.payload, Workspace) and isinstance(emptied.payload, Source)
            assert candidate.payload.files["{source_path}"] == emptied.payload.text, probe.id


def discover_one(operator: str) -> MutationOperator:
    return next(o for o in discover() if o.id == operator)


@pytest.mark.parametrize("probe_id", [p.id for p in probes() if p.expect == "reject"])
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


def test_a_positive_control_manifest_carries_no_ground() -> None:
    """The accepting side of the loader: a correct submission is not accused of anything."""
    accept = _GOOD.replace('ground = "structural"\n', "").replace('expect = "reject"', 'expect = "accept"')
    (probe,) = parse(accept.replace('solution = "no-op"', 'solution = "reference"'))
    assert (probe.expect, probe.ground) == ("accept", None)


@pytest.mark.parametrize(
    ("breakage", "old", "new"),
    [
        ("no template table", "[probe.template]\n", "[probe.not_a_template]\n"),
        ("no shape", 'shapes = ["container"]', "shapes = []"),
        ("weakness not a list", 'weakness = ["BGW-111"]', 'weakness = "BGW-111"'),
        ("empty title", 'title = "Write the maximum reward"', 'title = ""'),
        ("template file is not a name", '"{reward_path}" = "reward_max.txt"', '"{reward_path}" = 1'),
    ],
)
def test_more_malformed_manifests_are_refused(breakage: str, old: str, new: str) -> None:
    assert old in _GOOD, breakage
    with pytest.raises(ValueError):
        parse(_GOOD.replace(old, new, 1))


# --------------------------------------------------------------------------- which weakness a finding carries

_TWO = (
    _GOOD
    + """
[[probe]]
id = "acme/reward-read@1"
operator = "reward_read"
weakness = ["BGW-111", "BGW-126"]
title = "Read the reward"
shapes = ["container"]
ground = "structural"
expect = "reject"
maturity = "experimental"
battery = 2
sources = ["https://example.org/paper"]
[probe.template]
solution = "no-op"
parameters = []
[[probe.attribution]]
weakness = "BGW-126"
when_rejected = "acme/reward-write@1"
reason = "It ran and was checked."
"""
)


def test_a_finding_carries_the_first_weakness_unless_an_attribution_holds() -> None:
    probe = next(p for p in parse(_TWO) if p.id == "acme/reward-read@1")
    assert weakness_of(probe, set()) == "BGW-111"
    assert weakness_of(probe, {"acme/other@1"}) == "BGW-111"
    assert weakness_of(probe, {"acme/reward-write@1"}) == "BGW-126"


@pytest.mark.parametrize(
    ("breakage", "old", "new"),
    [
        ("not a list", "[[probe.attribution]]\n", "[probe.attribution]\n"),
        ("the first weakness", 'weakness = "BGW-126"\nwhen', 'weakness = "BGW-111"\nwhen'),
        ("not the probe's weakness", 'weakness = "BGW-126"\nwhen', 'weakness = "BGW-127"\nwhen'),
        ("not a probe ID", 'when_rejected = "acme/reward-write@1"', 'when_rejected = "reward-write"'),
        ("an unknown probe", 'when_rejected = "acme/reward-write@1"', 'when_rejected = "acme/nothing@1"'),
        ("the probe itself", 'when_rejected = "acme/reward-write@1"', 'when_rejected = "acme/reward-read@1"'),
        ("an extra key", 'reason = "It ran and was checked."', 'reason = "It ran and was checked."\nextra = 1'),
        ("no reason", 'reason = "It ran and was checked."', 'reason = ""'),
    ],
)
def test_an_attribution_breaking_one_rule_is_refused(breakage: str, old: str, new: str) -> None:
    assert old in _TWO, breakage
    with pytest.raises(ValueError):
        parse(_TWO.replace(old, new, 1))


def test_a_raising_program_paid_for_is_failure_scored_as_success_where_the_empty_one_was_not() -> None:
    """The grader ran the code and checked it, yet paid for an exception: the fix is to fail closed."""
    probe = probe_for("raise_not_implemented")
    assert probe is not None and probe.weakness == ("BGW-101", "BGW-126")
    assert weakness_of(probe, set()) == "BGW-101"
    assert weakness_of(probe, {"bohrin/empty-implementation@1"}) == "BGW-126"
    assert probe_for("drop_side_effect") is not None
