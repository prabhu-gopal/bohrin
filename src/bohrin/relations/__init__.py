"""Positive controls: the reference solution, and certified rewritings of it that a grader must accept.

The catalogue is discovered exactly like mutation operators: through an entry-point group,
with no privileged path for built-ins. A third party adds a relation — a formatting
convention, a certified refactoring — by publishing a package, not by patching Bohrin.

:func:`positive_controls` gives a task's controls: the reference unchanged first (the baseline;
if a grader rejects it, the task is excluded, never scored), then each certified rewriting that
differs from it and from the rewritings before it.
"""

from __future__ import annotations

from dataclasses import dataclass

from bohrin._plugins import RELATIONS, load_plugin_classes
from bohrin.ir.task import Source, Task
from bohrin.relations.base import Relation

#: Built-ins in the order they are tried: the least change first, so when two rewritings coincide
#: the credit goes to the smaller one. Appended to, never reordered.
_BUILTIN_ORDER: tuple[str, ...] = ("comment_free", "reformatted", "renamed_locals")

#: The relation name of the reference itself, the baseline every control is compared with.
BASELINE = "oracle"


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
    """``(relation_id, rendering)`` pairs for ``answer`` (a solution), duplicates removed.

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
        except Exception:  # a bad relation must never take down the catalogue
            continue
        if rendered is None or rendered in seen:
            continue
        seen.add(rendered)
        out.append((relation.id, rendered))
    return out


@dataclass(frozen=True, slots=True)
class Control:
    """A correct submission a correct grader must accept."""

    payload: Source
    #: The relation that produced it, or :data:`BASELINE` for the reference itself.
    relation: str
    #: Why it is correct: the relation's certification.
    certification: str

    @property
    def baseline(self) -> bool:
        """Whether this is the reference itself, which decides if the task can be scored at all."""
        return self.relation == BASELINE


def positive_controls(task: Task) -> tuple[Control, ...]:
    """The task's reference, then every certified rewriting of it; nothing when there is no reference."""
    reference = task.reference
    if not reference:
        return ()
    controls = [Control(Source(reference), BASELINE, "the task's own reference solution")]
    certifications = {relation.id: relation.certification for relation in discover()}
    seen = {reference.strip()}
    for relation_id, rendered in renderings(reference):
        # Surrounding blank lines are not a different program; sending one twice learns nothing.
        if rendered.strip() not in seen:
            seen.add(rendered.strip())
            controls.append(Control(Source(rendered), relation_id, certifications[relation_id]))
    return tuple(controls)


__all__ = ["BASELINE", "Control", "Relation", "discover", "positive_controls", "renderings"]
