"""The decisions file: ``.bohrin/decisions.toml``, a repository's record of what it decided about findings.

``bohrin ignore`` writes it, and it is committed, so a decision is shared by the whole team: Google
moved from per-user to project-level suppression because per-user suppression hid problems from
everyone else. Its format is open, so any tool can read and write it.

A decision is about one finding, by its ``BF-`` ID, and is one of two actions:

* ``ignore``: the team does not want to see this finding. It stops being shown, and it counts in
  the probe's published dismissal rate. It says nothing about whether the finding is right.
* ``dispute``: the team says the finding is wrong. It stays visible, marked disputed, until the
  dispute is resolved; in the error rate it counts neither way until then.

Every decision keeps its **reason**, because reasons are how a broken check is found: a study of
suppression annotations found developers suppress mainly to silence false positives. A decision
may **expire**; after that date the finding shows again. A date that cannot be read is refused,
never taken as "no expiry": an ignore that silently lasts forever is the failure this avoids.
No field names a person; the repository's history already records who changed the file.

Each decision maps onto a SARIF suppression (``kind`` external; ``status`` accepted for an ignore,
underReview for a dispute; the reason as its justification), so code-scanning tools read it too.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from bohrin.evidence import _strict as strict
from bohrin.spec.ids import FINDING_ID

#: Where the file lives in a repository.
PATH = ".bohrin/decisions.toml"
VERSION = 1
ACTIONS = ("ignore", "dispute")


@dataclass(frozen=True, slots=True)
class Decision:
    """What a repository decided about one finding."""

    finding: str
    action: str
    reason: str
    decided: date
    expires: date | None = None

    def active(self, today: date) -> bool:
        """Whether the decision still holds on ``today``: it has not expired."""
        return self.expires is None or today < self.expires

    def to_sarif_suppression(self) -> dict[str, Any]:
        """The decision as a SARIF 2.1.0 suppression object."""
        return {
            "kind": "external",
            "status": "accepted" if self.action == "ignore" else "underReview",
            "justification": self.reason,
        }


def _date(value: Any, where: str) -> date:
    # A TOML local date reads as a date; a date-time or a string is not one.
    if not isinstance(value, date) or hasattr(value, "hour"):
        raise ValueError(f"{where}: expected a date such as 2026-10-01, written without quotes")
    return value


def _decision(value: Any, where: str) -> Decision:
    entry = strict.obj(
        value,
        where,
        frozenset({"finding", "action", "reason", "decided", "expires"}),
        frozenset({"finding", "action", "reason", "decided"}),
    )
    action = strict.string(entry["action"], f"{where}.action")
    if action not in ACTIONS:
        raise ValueError(f"{where}.action: must be one of {list(ACTIONS)}")
    reason = strict.string(entry["reason"], f"{where}.reason", empty=False)
    if not reason.strip():
        raise ValueError(f"{where}.reason: say why; the reason is how a broken check is found")
    decided = _date(entry["decided"], f"{where}.decided")
    expires = _date(entry["expires"], f"{where}.expires") if "expires" in entry else None
    if expires is not None and expires <= decided:
        raise ValueError(f"{where}.expires: must be after the decision date")
    return Decision(
        finding=strict.string(entry["finding"], f"{where}.finding", pattern=FINDING_ID),
        action=action,
        reason=reason,
        decided=decided,
        expires=expires,
    )


def read_decisions(text: str) -> tuple[Decision, ...]:
    """Every decision in a decisions file, read strictly, or ``ValueError`` naming the one at fault."""
    try:
        data = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, RecursionError) as exc:
        raise ValueError(f"not TOML: {exc}") from exc
    return read_decisions_data(data)


def read_decisions_data(data: Any) -> tuple[Decision, ...]:
    """The decisions in an already parsed file (TOML dates as ``datetime.date``)."""
    top = strict.obj(data, PATH, frozenset({"version", "decision"}), frozenset({"version"}))
    if strict.integer(top["version"], "version") != VERSION:
        raise ValueError(f"version: this release reads version {VERSION}")
    raw = top.get("decision", [])
    if not isinstance(raw, list):
        raise ValueError("decision: write each one as a [[decision]] table")
    decisions = tuple(_decision(entry, f"decision[{index}]") for index, entry in enumerate(raw))
    seen: set[str] = set()
    for decision in decisions:
        if decision.finding in seen:
            raise ValueError(f"{decision.finding} has two decisions; keep one")
        seen.add(decision.finding)
    return decisions


def active(decisions: Iterable[Decision], today: date) -> Mapping[str, Decision]:
    """The decisions that hold on ``today``, by finding ID."""
    return {d.finding: d for d in decisions if d.active(today)}


def _quote(text: str) -> str:
    """A TOML basic string: backslash and quote escaped, anything unprintable as a code point."""
    out = []
    for ch in text:
        if ch in ('"', "\\"):
            out.append("\\" + ch)
        elif ch.isprintable():
            out.append(ch)
        elif ord(ch) <= 0xFFFF:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(f"\\U{ord(ch):08x}")
    return '"' + "".join(out) + '"'


def format_decisions(decisions: Iterable[Decision]) -> str:
    """The decisions file for ``decisions``, sorted by finding ID so a change reads as a small diff."""
    lines = [
        f"# What this repository decided about Bohrin findings. See {PATH} in docs/SPEC.md.",
        f"version = {VERSION}",
    ]
    for d in sorted(decisions, key=lambda d: d.finding):
        lines += ["", "[[decision]]", f"finding = {_quote(d.finding)}", f"action = {_quote(d.action)}"]
        lines += [f"reason = {_quote(d.reason)}", f"decided = {d.decided.isoformat()}"]
        if d.expires is not None:
            lines.append(f"expires = {d.expires.isoformat()}")
    return "\n".join(lines) + "\n"


__all__ = [
    "ACTIONS",
    "PATH",
    "VERSION",
    "Decision",
    "active",
    "format_decisions",
    "read_decisions",
    "read_decisions_data",
]
