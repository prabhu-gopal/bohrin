"""Certified meaning-preserving rewritings of an answer.

The catalogue is discovered exactly like probes, adapters and mutation operators: through
an entry-point group, with no privileged path for the built-ins. A third party adds a
relation — a domain's own notation, a unit convention, a house answer format — by
publishing a package, not by patching Bohrin.
"""

from __future__ import annotations

from bohrin._plugins import RELATIONS, load_plugin_classes
from bohrin.relations.base import Relation

#: Built-ins in the order they are tried. Presentational rewritings first, because the
#: published category-level evidence says those are what verifiers actually reject.
_BUILTIN_ORDER = (
    "verbatim",
    "stripped",
    # Punctuation and layout lead the presentational group: a category-level audit of four
    # verifiers attributes 93.0% of in-contract failures on one configuration to whitespace
    # and punctuation, with a trailing period or newline the dominant individual cause.
    "trailing_period",
    "trailing_newline",
    "boxed",
    "boxed_math",
    "prose",
    "prose_boxed",
    "emphasis",
    "boxed_text",
    "inline_math",
    "decimal_point",
    "trailing_zeros_dropped",
    "latex_fraction",
    "display_fraction",
    "braced_sqrt_argument",
)


def discover() -> list[Relation]:
    """Every registered relation, instantiated, built-ins in catalogue order.

    Third-party relations follow the built-ins, sorted by id. They are appended rather
    than interleaved so that adding a plugin cannot reorder — and therefore cannot change
    the meaning of — an existing audit's baseline search.
    """
    found = {name: cls for name, cls in load_plugin_classes(RELATIONS).items() if issubclass(cls, Relation)}
    ordered = [*(n for n in _BUILTIN_ORDER if n in found), *sorted(set(found) - set(_BUILTIN_ORDER))]
    out: list[Relation] = []
    for name in ordered:
        inst = found[name]()
        if not inst.id:
            inst.id = name
        out.append(inst)
    return out


def renderings(answer: str) -> list[tuple[str, str]]:
    """``(relation_id, rendering)`` pairs for ``answer``, duplicates removed.

    Deduplication is by the rendered string: two relations that agree on a given answer
    produce one submission, because sending the same bytes twice spends a scoring call
    against someone else's environment and learns nothing. The *first* relation to produce
    a rendering keeps the credit, which is why catalogue order is fixed.
    """
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for relation in discover():
        try:
            rendered = relation.render(answer)
        except Exception:  # a bad relation must never take down an audit
            continue
        if rendered is None or rendered in seen:
            continue
        seen.add(rendered)
        out.append((relation.id, rendered))
    return out


__all__ = ["Relation", "discover", "renderings"]
