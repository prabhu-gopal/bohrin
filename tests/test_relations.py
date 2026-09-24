"""The metamorphic relation catalogue: the seam positive controls come through.

A relation claims that its rewriting preserves meaning. The consequence of a wrong claim is
specific and severe: Bohrin would report a verifier for rejecting a solution that was never
equivalent in the first place — a false accusation, arrived at from the other direction. So
the catalogue's own rules are tested here with test doubles registered the way a third party
registers: ordering is stable, duplicates are dropped, and one broken relation cannot take
the catalogue down.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import bohrin.relations as relations
from bohrin.relations import Relation, discover, renderings


class _Verbatim(Relation):
    certification = "the solution unchanged is the solution"

    def render(self, answer: str) -> str | None:
        return answer


class _Stripped(Relation):
    certification = "surrounding whitespace is not part of a program"

    def render(self, answer: str) -> str | None:
        return answer.strip() + "\n"


class _Exploding(Relation):
    certification = "test double"

    def render(self, answer: str) -> str | None:
        raise RuntimeError("boom")


@pytest.fixture
def registered(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Register relations through the same loader an installed plugin reaches."""
    found = {"stripped": _Stripped, "verbatim": _Verbatim, "exploding": _Exploding}
    monkeypatch.setattr(relations, "load_plugin_classes", lambda group: dict(found))
    yield


def test_the_built_ins_are_the_certified_positive_controls() -> None:
    assert [r.id for r in discover()] == ["comment_free", "reformatted", "renamed_locals"]
    assert renderings("def f():\n    return 1\n") == [], "nothing to rewrite here"


@pytest.mark.usefixtures("registered")
def test_registered_relations_are_discovered_in_id_order_with_their_ids() -> None:
    found = discover()

    assert [r.id for r in found] == ["exploding", "stripped", "verbatim"]
    assert all(isinstance(r, Relation) and r.certification.strip() for r in found)


@pytest.mark.usefixtures("registered")
def test_a_broken_relation_cannot_take_down_the_catalogue_and_duplicates_are_dropped() -> None:
    source = "def f():\n    return 1\n"

    # `stripped` renders the same bytes as `verbatim` here; the first in order keeps the credit.
    assert renderings(source) == [("stripped", source)]
