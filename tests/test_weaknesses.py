"""The weakness list: its identifiers are permanent, its data is checked, its page is current.

An identifier is a promise to everyone who has cited it. So the list is tested for the two ways
that promise breaks: an ID disappearing or being reused, and a malformed entry reaching the
published page. The loader's checks are each exercised by a list that breaks exactly one rule.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bohrin.ir.task import Ground, Shape
from bohrin.spec.weaknesses import EVIDENCE, PROVIDES, parse, render_markdown, weakness_list

DOCS = Path(__file__).resolve().parents[1] / "docs" / "WEAKNESSES.md"

#: Every ID ever published, with the name it was published under. An ID may be deprecated but
#: never removed, renumbered or reused for a different weakness, so this only ever grows.
PUBLISHED = {
    "BGW-101": "Trivial implementation",
    "BGW-102": "Exit before the checks",
    "BGW-103": "Equality spoofing",
    "BGW-104": "Hard-coded expected outputs",
    "BGW-105": "State recorded across calls",
    "BGW-106": "Dead code for a static check",
    "BGW-107": "Letter of the specification, not its intent",
    "BGW-108": "Test-framework hook",
    "BGW-109": "Tests edited, deleted or skipped",
    "BGW-110": "Hijacked tool",
    "BGW-111": "Direct write to the reward file",
    "BGW-112": "Result parser replaced",
    "BGW-113": "Measurement tampering",
    "BGW-114": "Shared state tampered through a side channel",
    "BGW-115": "Solution in the task text",
    "BGW-116": "Reference or verifier readable at run time",
    "BGW-117": "Future repository state",
    "BGW-118": "Solution fetched from the network",
    "BGW-119": "Tests too weak",
    "BGW-120": "Tests too narrow",
    "BGW-121": "Specification contradicts the tests",
    "BGW-122": "Partial credit rewards the wrong approach",
    "BGW-123": "Output checker too lenient",
    "BGW-124": "Reference solution wrong",
    "BGW-125": "Evaluation that does not evaluate",
    "BGW-126": "Failure scored as success",
    "BGW-127": "Nondeterministic grader",
    "BGW-128": "Aggregation defect",
    "BGW-129": "Grader executes agent-controlled data",
    "BGW-130": "Agent and grader share an environment",
    "BGW-131": "Evaluator paths writable by the agent",
    "BGW-132": "Excessive permissions or network egress",
    "BGW-133": "Evaluation too small or noisy",
    "BGW-134": "Numeric tolerance too loose for the output",
    "BGW-135": "Proof checker accepts incomplete proofs",
    "BGW-136": "Execution equivalence on one database",
    "BGW-137": "Pseudo-tested code",
    "BGW-138": "Proxy-state check",
}


# --------------------------------------------------------------------------- the shipped list


def test_no_published_id_is_ever_removed_or_renamed() -> None:
    shipped = {w.id: w.name for w in weakness_list().weaknesses}
    missing = sorted(set(PUBLISHED) - set(shipped))
    renamed = sorted(i for i in PUBLISHED if i in shipped and shipped[i] != PUBLISHED[i])
    assert missing == [], f"published IDs removed (deprecate them instead): {missing}"
    assert renamed == [], f"published IDs now name something else: {renamed}"


def test_every_shipped_id_is_recorded_as_published() -> None:
    """A new class is added here in the same change, so the list above stays complete."""
    unrecorded = sorted({w.id for w in weakness_list().weaknesses} - set(PUBLISHED))
    assert unrecorded == [], f"add these to PUBLISHED: {unrecorded}"


def test_the_list_is_in_id_order_and_every_family_is_used() -> None:
    wl = weakness_list()
    numbers = [w.number for w in wl.weaknesses]
    assert numbers == sorted(numbers)
    assert {w.family for w in wl.weaknesses} == set(wl.families)


def test_a_class_with_a_ground_can_produce_a_wrong_submission() -> None:
    """Grounds belong to evidence that is a wrong submission, never to a statistic or a risk."""
    submission_evidence = {"reproduction", "differentiating-input", "differentiating-observation", "fact"}
    for w in weakness_list().weaknesses:
        if w.grounds:
            assert set(w.evidence) & submission_evidence, w.id


def test_every_published_taxonomy_category_is_crosswalked() -> None:
    """A crosswalk that skips a category leaves a reader of that vocabulary with no answer."""
    crosswalks = {cw.key: cw for cw in weakness_list().crosswalks}
    assert set(crosswalks["terminal-wrench"].map) == {
        "hollow-implementation",
        "output-spoofing",
        "constraint-loophole",
        "structural-extraction",
        "binary-hijacking",
        "algorithmic-simplification",
        "mutable-input-tampering",
        "keyword-gaming",
        "metric-spoofing",
        "security-downgrading",
        "deceptive-rationalization",
    }
    assert len(crosswalks["harbor-rubric"].map) == 11


def test_the_published_page_is_generated_from_the_list() -> None:
    if not DOCS.is_file():
        pytest.skip("no docs/ in this checkout")
    assert DOCS.read_text(encoding="utf-8") == render_markdown(), (
        "docs/WEAKNESSES.md is stale: python -m bohrin.spec > docs/WEAKNESSES.md"
    )


def test_every_class_on_the_page_has_its_own_anchor() -> None:
    page = render_markdown()
    for w in weakness_list().weaknesses:
        assert re.search(rf"^### {w.id}$", page, re.MULTILINE), w.id


# --------------------------------------------------------------------------- the loader's checks

_GOOD = """
version = 1
[families]
f = "A family"
[[weakness]]
id = "BGW-101"
name = "A weakness"
family = "f"
mechanism = "Why it matters."
shapes = ["program"]
grounds = ["structural"]
evidence = ["reproduction"]
provides = ["template"]
fix = "How to close it."
sources = ["https://example.org/paper"]
"""


def test_a_well_formed_list_parses() -> None:
    wl = parse(_GOOD)
    (w,) = wl.weaknesses
    assert (w.id, w.shapes, w.grounds, w.status) == ("BGW-101", (Shape.PROGRAM,), (Ground.STRUCTURAL,), "active")


@pytest.mark.parametrize(
    ("breakage", "old", "new"),
    [
        ("malformed ID", 'id = "BGW-101"', 'id = "BGW-0101"'),
        ("unknown family", 'family = "f"', 'family = "g"'),
        ("unknown shape", 'shapes = ["program"]', 'shapes = ["spreadsheet"]'),
        ("no shape", 'shapes = ["program"]', "shapes = []"),
        ("unknown ground", 'grounds = ["structural"]', 'grounds = ["vibes"]'),
        ("unknown evidence", 'evidence = ["reproduction"]', 'evidence = ["a hunch"]'),
        ("no evidence", 'evidence = ["reproduction"]', "evidence = []"),
        ("unknown provision", 'provides = ["template"]', 'provides = ["exploit"]'),
        ("no source", 'sources = ["https://example.org/paper"]', "sources = []"),
        ("non-https source", 'sources = ["https://example.org/paper"]', 'sources = ["http://example.org/paper"]'),
        ("empty mechanism", 'mechanism = "Why it matters."', 'mechanism = " "'),
        ("unknown status", 'fix = "How to close it."', 'fix = "How to close it."\nstatus = "retired"'),
        ("no version", "version = 1", "version = 0"),
    ],
)
def test_a_list_breaking_one_rule_is_refused(breakage: str, old: str, new: str) -> None:
    assert old in _GOOD, breakage
    with pytest.raises(ValueError):
        parse(_GOOD.replace(old, new, 1))


def test_a_reused_id_is_refused() -> None:
    body = _GOOD.split("[[weakness]]", 1)[1]
    with pytest.raises(ValueError, match="duplicate"):
        parse(_GOOD + "[[weakness]]" + body)


def test_a_crosswalk_to_an_unknown_id_is_refused() -> None:
    crosswalk = '\n[crosswalk.x]\ntitle = "X"\nsource = "https://example.org"\n[crosswalk.x.map]\na = ["BGW-999"]\n'
    with pytest.raises(ValueError, match="unknown IDs"):
        parse(_GOOD + crosswalk)


def test_the_vocabularies_are_described() -> None:
    """Every evidence kind and provision a class can name has a sentence on the published page."""
    page = render_markdown()
    for key in [*EVIDENCE, *PROVIDES]:
        assert f"**{key}**" in page, key
