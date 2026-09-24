"""The metamorphic relation contract.

A **metamorphic relation** states how a verifier's verdict must change — or must not
change — when its input is transformed in a known way. It is the standard answer to the
*oracle problem*: you cannot always say whether one output is correct, but you can say
that two outputs must agree.

That is exactly Bohrin's position, and it unifies both halves of the Verification Gap:

* **Meaning-preserving** transformation, verdict flips to reject
  :math:`\\Rightarrow` a **false negative**. The declared solution, rewritten, must
  still pass.
* **Meaning-destroying** transformation, verdict stays accept
  :math:`\\Rightarrow` a **false positive**. A solution that does no work must not pass.

Only the first kind lives here. Meaning-destroying transformations are mutation
operators (:mod:`bohrin.mutate`), which already have their own contract and their own
``Ground`` obligation.

**The soundness rule, and it is the whole point of the module.** A relation may only
declare itself meaning-preserving when that is true *by construction* — a rewriting whose
equivalence follows from the form of the solution, not from a guess about the verifier.
A program with its comments removed is the same program; one with a branch negated is
not. Get this wrong in the permissive direction and Bohrin accuses a correct verifier of
rejecting a correct solution — a false accusation, with the sign reversed.

Consequently a relation is *partial*: it declares the solutions it applies to, and returns
nothing for the rest. Removing comments means something for a program that has them and
nothing for one that has none, and silence is the correct output rather than a guess.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Relation(ABC):
    """One certified meaning-preserving rewriting of a solution.

    Subclass, set :attr:`id`, and implement :meth:`render`. Third parties register through
    the ``bohrin.relations`` entry-point group; there is no privileged path for the
    built-ins.
    """

    #: Stable identifier, reported in findings. Filled from the entry-point name if unset.
    id: str = ""

    #: One sentence naming *why* the rewriting preserves meaning. This is not decoration:
    #: it is the argument a reader checks when deciding whether to believe a finding.
    certification: str = ""

    @abstractmethod
    def render(self, answer: str) -> str | None:
        """The solution, rewritten — or ``None`` when this relation does not apply.

        Returning the solution unchanged is treated the same as ``None`` by the catalogue:
        a rendering identical to one already tried costs a scoring call and buys nothing.
        """

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"<Relation {self.id or type(self).__name__}>"


__all__ = ["Relation"]
