"""The built-in catalogue.

Every relation here is meaning-preserving *by construction*, and the ordering is not
arbitrary: it follows the measured causes of verifier false negatives rather than what
was convenient to write. A category-level audit of four widely-used verifiers over
307,420 verdicts found self-validation — a verifier accepting certified-equivalent
renderings of its own ground truth — ranging from 53.8% to 95.2%, with **whitespace and
punctuation alone accounting for 93.0%** of in-contract failures on one verifier and
74.1% on another, and fractions responsible for a further 25.4% on a third.

So the cheap presentational rewritings come first. They are the ones that actually fire.

**What is deliberately absent.** A thousands separator (``1000`` → ``1,000``) is a common
human rendering and is *not* included, because the comma is a decimal separator in much
of the world: the rewriting is only meaning-preserving under an assumption about locale,
and an assumption is exactly what a certification may not contain.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from bohrin.relations.base import Relation

#: Characters that already close an answer. A carrier sentence does not add a full stop
#: after one of these, and `trailing_period` does not fire on one: `42..` and `why?.` are
#: strings no submission contains, and a rendering nobody writes tests nothing. A verifier
#: refusing one would be counted as refusing its own answer, which it never had the chance
#: to accept.
_SENTENCE_END = ".!?,;:"

#: A bare fraction, e.g. ``3/4`` or ``-3 / 4``. Deliberately strict: anything more
#: elaborate is not confidently a fraction, and a wrong guess here is unsound.
_FRACTION = re.compile(r"^(-?\d+)\s*/\s*(\d+)$")

#: ``\sqrt`` applied to a single unbraced token, e.g. ``\sqrt2``. LaTeX takes exactly one
#: token as the argument, so bracing that token is a pure notational change. Deliberately
#: narrow: for a multi-character argument the unbraced form means something *different*
#: (``\sqrt12`` is the square root of 1, followed by a 2), so rewriting it would not be
#: meaning-preserving and this relation must not fire.
_SQRT_TOKEN = re.compile(r"\\sqrt(?![a-zA-Z{])\s*([0-9a-zA-Z])")


def _number(answer: str) -> Decimal | None:
    """The answer as an exact decimal, or ``None`` if it is not plainly a number.

    ``Decimal`` rather than ``float`` on purpose: the relations below rewrite the
    *presentation* of a number, and float round-tripping would silently change the value
    for answers with many significant digits — turning a meaning-preserving relation into
    a meaning-changing one.
    """
    text = answer.strip()
    if not text or len(text) > 64:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


class Verbatim(Relation):
    id = "verbatim"
    certification = "the stored answer itself, unmodified — the identity relation"

    def render(self, answer: str) -> str | None:
        return answer


class Stripped(Relation):
    id = "stripped"
    certification = "surrounding whitespace carries no mathematical or semantic content"

    def render(self, answer: str) -> str | None:
        return answer.strip()


class Boxed(Relation):
    id = "boxed"
    certification = "LaTeX \\boxed{} marks a final answer; it does not alter the answer"

    def render(self, answer: str) -> str | None:
        return f"\\boxed{{{answer.strip()}}}" if answer.strip() else None


class BoxedMath(Relation):
    id = "boxed_math"
    certification = "inline math delimiters set the typesetting mode, not the value"

    def render(self, answer: str) -> str | None:
        return f"$\\boxed{{{answer.strip()}}}$" if answer.strip() else None


class BoxedText(Relation):
    id = "boxed_text"
    certification = "\\text{} selects an upright font inside math mode; the content is unchanged"

    def render(self, answer: str) -> str | None:
        return f"\\boxed{{\\text{{{answer.strip()}}}}}" if answer.strip() else None


class InlineMath(Relation):
    id = "inline_math"
    certification = "inline math delimiters set the typesetting mode, not the value"

    def render(self, answer: str) -> str | None:
        return f"${answer.strip()}$" if answer.strip() else None


class Prose(Relation):
    id = "prose"
    certification = "a natural-language carrier sentence; the answer it announces is unchanged"

    def render(self, answer: str) -> str | None:
        text = answer.strip()
        if not text:
            return None
        stop = "" if text[-1] in _SENTENCE_END else "."
        return f"The answer is {text}{stop}"


class ProseBoxed(Relation):
    id = "prose_boxed"
    certification = "a carrier sentence around a boxed answer; both are presentational"

    def render(self, answer: str) -> str | None:
        text = answer.strip()
        if not text:
            return None
        stop = "" if text[-1] in _SENTENCE_END else "."
        return f"The answer is \\boxed{{{text}}}{stop}"


class Emphasis(Relation):
    id = "emphasis"
    certification = "Markdown emphasis is formatting; it does not alter the answer"

    def render(self, answer: str) -> str | None:
        return f"**{answer.strip()}**" if answer.strip() else None


class DecimalPoint(Relation):
    id = "decimal_point"
    certification = "an integer written with an explicit tenths place is the same number: 70 = 70.0"

    def render(self, answer: str) -> str | None:
        value = _number(answer)
        if value is None or value != value.to_integral_value():
            return None
        return f"{value.to_integral_value()}.0"


class TrailingZerosDropped(Relation):
    id = "trailing_zeros_dropped"
    certification = "trailing zeros after a decimal point do not change the value: 70.0 = 70"

    def render(self, answer: str) -> str | None:
        value = _number(answer)
        if value is None or "." not in answer.strip():
            return None
        # `f` formatting is load-bearing. Decimal.normalize() strips the trailing zeros but
        # renders the result in exponent form -- Decimal("70.0").normalize() is 7E+1, and
        # str() of that is "7E+1". Numerically equal, but scientific notation is a
        # different rewriting than the one certified above, so submitting it would test a
        # relation this class does not claim. Fixed-point formatting keeps the promise.
        return f"{value.normalize():f}"


class LatexFraction(Relation):
    id = "latex_fraction"
    certification = "\\frac{a}{b} is the standard typesetting of the fraction a/b"

    def render(self, answer: str) -> str | None:
        match = _FRACTION.match(answer.strip())
        return f"\\frac{{{match.group(1)}}}{{{match.group(2)}}}" if match else None


class TrailingPeriod(Relation):
    id = "trailing_period"
    certification = "a sentence-final period is punctuation; it does not alter the answer"

    def render(self, answer: str) -> str | None:
        """The answer with a full stop after it.

        This is the single highest-yield rendering in the catalogue. A category-level audit
        of four widely-used verifiers found whitespace and punctuation responsible for 93.0%
        of in-contract failures on one configuration, with a trailing period or newline the
        dominant individual cause -- a correct answer rejected for the punctuation a model
        naturally writes at the end of a sentence.

        Not applied to an answer that already ends in punctuation: appending to ``42.`` or
        ``Paris!`` produces a string no one writes, which tests nothing a real submission
        would exercise.
        """
        text = answer.strip()
        if not text or text[-1] in _SENTENCE_END:
            return None
        return f"{text}."


class TrailingNewline(Relation):
    id = "trailing_newline"
    certification = "a line break after the answer is layout; it does not alter the answer"

    def render(self, answer: str) -> str | None:
        """The answer followed by a newline.

        Distinct from `stripped`, which removes surrounding whitespace from an answer that
        has it. This *adds* the trailing newline a model emits at the end of a reply, which
        the same audit names alongside the trailing period as a dominant cause of correct
        answers being refused. A verifier that strips before comparing is unaffected; one
        that compares raw strings is not, and that is the difference being measured.
        """
        text = answer.strip()
        return f"{text}\n" if text else None


class DisplayFraction(Relation):
    id = "display_fraction"
    certification = "\\dfrac selects display style for a fraction; \\frac and \\dfrac render the same value"

    def render(self, answer: str) -> str | None:
        """``\\frac`` rewritten as ``\\dfrac``.

        Math-mode formatting is the stratum with the highest measured false-negative rate
        after whitespace -- 48.8% on one verifier -- and the display-style variant is the
        commonest way a model writes the same fraction differently.
        """
        text = answer.strip()
        if "\\frac" not in text or "\\dfrac" in text:
            return None
        return text.replace("\\frac", "\\dfrac")


class BracedSqrtArgument(Relation):
    id = "braced_sqrt_argument"
    certification = "\\sqrt takes one token as its argument; bracing that token is notation, not value"

    def render(self, answer: str) -> str | None:
        """``\\sqrt2`` rewritten as ``\\sqrt{2}``.

        Square-root notation is a measured stratum in its own right, at 35.1% on one
        verifier. Only a single-token argument is rewritten, because that is the only case
        where the two forms are equivalent: ``\\sqrt12`` is *not* the square root of twelve,
        so a broader rewriting would change the meaning it claims to preserve.
        """
        text = answer.strip()
        if not text:
            return None
        rendered = _SQRT_TOKEN.sub(r"\\sqrt{\1}", text)
        return rendered if rendered != text else None


__all__ = [
    "Boxed",
    "BoxedMath",
    "BoxedText",
    "BracedSqrtArgument",
    "DecimalPoint",
    "DisplayFraction",
    "Emphasis",
    "InlineMath",
    "LatexFraction",
    "Prose",
    "ProseBoxed",
    "Stripped",
    "TrailingNewline",
    "TrailingPeriod",
    "TrailingZerosDropped",
    "Verbatim",
]
