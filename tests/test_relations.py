"""The metamorphic relation catalogue.

A relation claims that its rewriting preserves meaning. Every test here exists to keep
that claim true, because the consequence of a wrong one is specific and severe: Bohrin
would report a verifier for rejecting an answer that was never equivalent in the first
place — a false accusation, arrived at from the other direction.
"""

from __future__ import annotations

import pytest

from bohrin.relations import Relation, discover, renderings
from bohrin.relations.builtin import (
    BracedSqrtArgument,
    DecimalPoint,
    DisplayFraction,
    LatexFraction,
    TrailingNewline,
    TrailingPeriod,
    TrailingZerosDropped,
    Verbatim,
)


def test_the_catalogue_is_discovered_through_the_entry_point_seam() -> None:
    """Built-ins take the same route a third party does — Gate 1 requires no patching."""
    found = discover()

    # Punctuation and layout sit directly behind the identity relation because the
    # published category-level evidence puts them at the top of the false-negative budget.
    assert [r.id for r in found][:4] == ["verbatim", "stripped", "trailing_period", "trailing_newline"]
    assert all(isinstance(r, Relation) for r in found)
    assert len(found) >= 16


def test_every_relation_states_why_it_preserves_meaning() -> None:
    """The certification is the argument a reader checks before believing a finding.

    A relation without one is an assertion, and an assertion is what this module exists
    to replace.
    """
    for relation in discover():
        assert relation.certification.strip(), f"{relation.id} claims equivalence without an argument"
        assert relation.id, "a relation must be identifiable in a finding"


def test_a_relation_that_does_not_apply_stays_silent() -> None:
    """Partiality is the soundness mechanism: silence beats a guess.

    ``trailing_zeros_dropped`` means something for ``70.0`` and nothing for ``banana``.
    Inventing a rendering for the second is how a catalogue starts lying.
    """
    assert TrailingZerosDropped().render("banana") is None
    assert DecimalPoint().render("banana") is None
    assert LatexFraction().render("banana") is None
    assert DecimalPoint().render("3.5") is None, "3.5 is not an integer; the tenths place is not free"


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("70.0", "70"), ("70.500", "70.5"), ("1000.0", "1000"), ("0.10", "0.1")],
)
def test_trailing_zeros_are_dropped_without_scientific_notation(answer: str, expected: str) -> None:
    """The bug this pins was real and would have produced nonsense submissions.

    ``Decimal("70.0").normalize()`` is ``7E+1``, and ``str()`` of that is ``"7E+1"``.
    Numerically equal, but scientific notation is a *different* rewriting than the one
    this relation certifies — so submitting it would test a claim the catalogue does not
    make, and a rejection would be reported against a promise never given.
    """
    assert TrailingZerosDropped().render(answer) == expected


def test_renderings_are_deduplicated() -> None:
    """Two relations agreeing on one answer must cost one scoring call, not two.

    Every rendering is a real submission against someone else's environment.
    """
    out = renderings("x")
    assert len(out) == len({rendering for _id, rendering in out})


def test_the_verbatim_answer_is_always_first_and_never_altered() -> None:
    """A verifier doing exact string comparison must see the stored value untouched.

    Stripping it first would fail the baseline on a task that is perfectly scoreable.
    """
    assert renderings("  70  ")[0] == ("verbatim", "  70  ")
    assert Verbatim().render("  70  ") == "  70  "


def test_numeric_relations_preserve_the_value() -> None:
    """The property that makes them certifiable, asserted rather than assumed."""
    from decimal import Decimal

    for answer in ("70", "0", "-3", "1000000", "12.50"):
        for _id, rendered in renderings(answer):
            bare = rendered.strip("$*").replace("\\boxed{", "").replace("}", "")
            bare = bare.replace("The answer is ", "").rstrip(".")
            try:
                value = Decimal(bare)
            except Exception:
                continue  # a prose or LaTeX carrier, checked by construction elsewhere
            assert value == Decimal(answer), f"{_id} changed {answer!r} into {rendered!r}"


def test_the_legacy_helper_still_returns_a_flat_list() -> None:
    """`reference_renderings` is used by the adapter and is now a view onto the catalogue."""
    from bohrin.adapters.verifiers_v1 import reference_renderings

    flat = reference_renderings("70")
    assert flat == [rendering for _id, rendering in renderings("70")]
    assert flat[0] == "70", "the unmodified answer must still come first"
    assert "\\boxed{70}" in flat, "the rendering that made aime25 measurable must survive"


def test_a_broken_third_party_relation_cannot_take_down_an_audit() -> None:
    """One bad plugin must never stop the catalogue, the same rule discovery follows."""

    class Exploding(Relation):
        id = "exploding"
        certification = "test double"

        def render(self, answer: str) -> str | None:
            raise RuntimeError("boom")

    import bohrin.relations as module

    original = module.discover
    module.discover = lambda: [Verbatim(), Exploding()]
    try:
        assert renderings("70") == [("verbatim", "70")]
    finally:
        module.discover = original


# --------------------------------------------------------- punctuation, layout, math mode


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("42", "42."), ("Paris", "Paris."), ("\\frac{1}{2}", "\\frac{1}{2}."), ("  42  ", "42.")],
)
def test_a_trailing_period_is_offered(answer: str, expected: str) -> None:
    """The highest-yield rendering in the catalogue, by published measurement.

    Whitespace and punctuation account for 93.0% of in-contract failures on one audited
    verifier configuration, with a trailing period or newline the dominant single cause.
    """
    assert TrailingPeriod().render(answer) == expected


@pytest.mark.parametrize("answer", ["42.", "Paris!", "why?", "a,", "b;", "c:", "", "   "])
def test_an_answer_already_ending_in_punctuation_is_left_alone(answer: str) -> None:
    """Appending to `42.` yields `42..`, a string no submission contains.

    A rendering nobody writes tests nothing, and a verifier refusing it would be reported
    for rejecting an answer it was never going to see.
    """
    assert TrailingPeriod().render(answer) is None


def test_a_trailing_newline_is_offered_and_is_not_the_stripped_relation() -> None:
    assert TrailingNewline().render("42") == "42\n"
    assert TrailingNewline().render("  42  ") == "42\n"
    assert TrailingNewline().render("   ") is None


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("\\frac{1}{2}", "\\dfrac{1}{2}"),
        ("\\frac{1}{2} + \\frac{3}{4}", "\\dfrac{1}{2} + \\dfrac{3}{4}"),
    ],
)
def test_frac_is_rewritten_to_display_style(answer: str, expected: str) -> None:
    assert DisplayFraction().render(answer) == expected


@pytest.mark.parametrize("answer", ["\\dfrac{1}{2}", "42", "Paris", ""])
def test_display_fraction_stays_silent_without_a_frac(answer: str) -> None:
    assert DisplayFraction().render(answer) is None


def test_a_single_token_sqrt_argument_is_braced() -> None:
    assert BracedSqrtArgument().render("\\sqrt2") == "\\sqrt{2}"
    assert BracedSqrtArgument().render("\\sqrt x") == "\\sqrt{x}"


def test_bracing_a_sqrt_takes_one_token_because_that_is_what_latex_takes() -> None:
    """`\\sqrt12` is the square root of 1 followed by a 2, not the square root of twelve.

    Bracing the single token it actually applies to preserves the meaning; rewriting it to
    `\\sqrt{12}` would change the value while claiming to preserve it — the exact error a
    certification exists to prevent.
    """
    assert BracedSqrtArgument().render("\\sqrt12") == "\\sqrt{1}2"


@pytest.mark.parametrize("answer", ["\\sqrt{2}", "42", "", "sqrt2"])
def test_braced_sqrt_stays_silent_when_there_is_nothing_to_brace(answer: str) -> None:
    assert BracedSqrtArgument().render(answer) is None


def test_every_new_rendering_round_trips_through_the_catalogue() -> None:
    """The new relations must actually reach `renderings()`, not just exist as classes."""
    ids = {rid for rid, _ in renderings("\\frac{1}{2}")}
    assert {"trailing_period", "trailing_newline", "display_fraction"} <= ids


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("42", "The answer is 42."),
        ("42.", "The answer is 42."),
        ("Paris.", "The answer is Paris."),
        ("why?", "The answer is why?"),
        ("wow!", "The answer is wow!"),
    ],
)
def test_a_carrier_sentence_does_not_double_the_punctuation(answer: str, expected: str) -> None:
    """`The answer is 42..` is a string no submission contains.

    Same standard the trailing-period relation is held to: a rendering nobody writes tests
    nothing, and a verifier refusing it would be counted as refusing its own answer when it
    was never given the chance to accept it.
    """
    from bohrin.relations.builtin import Prose

    assert Prose().render(answer) == expected


def test_a_boxed_carrier_sentence_does_not_double_the_punctuation() -> None:
    from bohrin.relations.builtin import ProseBoxed

    assert ProseBoxed().render("42") == "The answer is \\boxed{42}."
    assert ProseBoxed().render("why?") == "The answer is \\boxed{why?}"
