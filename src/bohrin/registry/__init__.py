"""The registry record: one public record of a defect in a coding grader or its harness.

A record is to a finding what a CVE record is to a bug report: the public, permanent form, with an
ID (``BVR-<year>-<number>``) a paper or an issue can cite. Field names follow the OSV schema where
they fit (``id``, ``aliases``, ``related``, ``summary``, ``details``, ``affected`` with OSV ranges
and events, ``references`` and ``credits`` with OSV's types, ``modified``, ``published``,
``withdrawn``, ``schema_version``), plus what a stranger needs to check the claim: the weakness
class, the probe, the submission as a digest (never its text), what the grader paid, the ground and
the reproduction script.

**The notification policy is checked, not only written down** (``docs/disclosure.md``). A record
is refused unless it was published at least 45 days after the maintainer was first told
privately, or the defect is fixed and the maintainer agreed to earlier publication. 45 days is
the CERT Coordination Center's default. A record names the artefact, never a person.

The reader applies the published schema, and three rules no JSON Schema can express: the dates
are real calendar dates, the 45-day rule, and every weakness ID is a class of the weakness list.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any

from bohrin.evidence import _strict as strict
from bohrin.evidence.finding import (  # one reader for the fields the two formats share
    Reproduction,
    Scored,
    Submission,
    _read_reproduction,
    _read_scored,
    _read_submission,
)
from bohrin.ir.task import Ground, Shape
from bohrin.spec.ids import FINDING_ID, PROBE_ID, RECORD_ID, WEAKNESS_ID
from bohrin.spec.weaknesses import weakness_list

REGISTRY_RECORD_SCHEMA = "https://bohrin.com/schema/registry-record/v1"
#: The days between first private contact with a maintainer and publication.
NOTICE_DAYS = 45
STATUSES = ("reported", "confirmed", "fixed", "disputed", "withdrawn")
ARTIFACT_KINDS = ("environment", "benchmark", "grader", "harness")
RANGE_TYPES = ("GIT", "SEMVER", "ECOSYSTEM")
EVENTS = ("introduced", "fixed", "last_affected", "limit")
REFERENCE_TYPES = (
    "ADVISORY", "ARTICLE", "DETECTION", "DISCUSSION", "REPORT", "FIX", "INTRODUCED", "GIT", "PACKAGE",
    "EVIDENCE", "WEB",
)  # fmt: skip
CREDIT_TYPES = (
    "FINDER", "REPORTER", "ANALYST", "COORDINATOR", "REMEDIATION_DEVELOPER", "REMEDIATION_REVIEWER",
    "REMEDIATION_VERIFIER", "TOOL", "SPONSOR", "OTHER",
)  # fmt: skip

_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]+)?Z")
_VERSION = re.compile(r"1\.[0-9]+\.[0-9]+")
_URL = re.compile(r"https?://.*")

_TOP = frozenset(
    {
        "$schema", "schema_version", "id", "aliases", "related", "modified", "published", "withdrawn", "summary",
        "details", "weakness", "probe", "findings", "affected", "submission", "score_received", "ground",
        "reproduce", "status", "numbering_authority", "disclosure", "references", "credits",
    }
)  # fmt: skip
_REQUIRED = frozenset(
    {
        "$schema", "schema_version", "id", "modified", "published", "summary", "weakness", "affected", "status",
        "numbering_authority", "disclosure",
    }
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class Artifact:
    """What has the defect. Never a person."""

    kind: str
    name: str
    repository: str | None = None


@dataclass(frozen=True, slots=True)
class Affected:
    """One affected artefact, the grader shape it has the defect in, and where (OSV ranges)."""

    artifact: Artifact
    shape: Shape
    #: ``(type, repo, events)`` per range; each event is ``(kind, version)``.
    ranges: tuple[tuple[str, str | None, tuple[tuple[str, str], ...]], ...] = ()
    versions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Record:
    """A registry record, read strictly. ``document`` is the record exactly as validated."""

    id: str
    status: str
    published: datetime
    modified: datetime
    maintainer_notified: datetime
    summary: str
    weakness: tuple[str, ...]
    affected: tuple[Affected, ...]
    submission: Submission | None
    score_received: Scored | None
    ground: Ground | None
    reproduce: Reproduction | None
    document: Mapping[str, Any]


def _time(value: Any, where: str) -> datetime:
    text = strict.string(value, where, pattern=_TIMESTAMP)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as exc:
        raise ValueError(f"{where}: {text!r} is not a real date and time") from exc


def _unique_strings(value: Any, where: str, pattern: re.Pattern[str] | None = None) -> tuple[str, ...]:
    items = strict.array(value, where, lambda v, w: strict.string(v, w, empty=False, pattern=pattern))
    if len(set(items)) != len(items):
        raise ValueError(f"{where}: lists an item twice")
    return items


def _choice(value: Any, where: str, choices: tuple[str, ...]) -> str:
    text = strict.string(value, where)
    if text not in choices:
        raise ValueError(f"{where}: must be one of {list(choices)}")
    return text


def _event(value: Any, where: str) -> tuple[str, str]:
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError(f"{where}: an event has exactly one of {list(EVENTS)}")
    ((kind, version),) = value.items()
    if kind not in EVENTS:
        raise ValueError(f"{where}: an event has exactly one of {list(EVENTS)}")
    return kind, strict.string(version, f"{where}.{kind}", empty=False)


def _range(value: Any, where: str) -> tuple[str, str | None, tuple[tuple[str, str], ...]]:
    entry = strict.obj(value, where, frozenset({"type", "repo", "events"}), frozenset({"type", "events"}))
    kind = _choice(entry["type"], f"{where}.type", RANGE_TYPES)
    repo = strict.string(entry["repo"], f"{where}.repo", pattern=_URL) if "repo" in entry else None
    if kind == "GIT" and repo is None:
        raise ValueError(f"{where}: a GIT range needs the repository it counts commits in")
    events = strict.array(entry["events"], f"{where}.events", _event)
    if not events:
        raise ValueError(f"{where}.events: needs at least one event")
    return kind, repo, events


def _affected(value: Any, where: str) -> Affected:
    entry = strict.obj(
        value, where, frozenset({"artifact", "shape", "ranges", "versions"}), frozenset({"artifact", "shape"})
    )
    raw = strict.obj(
        entry["artifact"], f"{where}.artifact", frozenset({"kind", "name", "repository"}), frozenset({"kind", "name"})
    )
    ranges = strict.array(entry["ranges"], f"{where}.ranges", _range) if "ranges" in entry else ()
    if "ranges" in entry and not ranges:
        raise ValueError(f"{where}.ranges: needs at least one range when given")
    return Affected(
        artifact=Artifact(
            kind=_choice(raw["kind"], f"{where}.artifact.kind", ARTIFACT_KINDS),
            name=strict.string(raw["name"], f"{where}.artifact.name", empty=False),
            repository=strict.string(raw["repository"], f"{where}.artifact.repository", pattern=_URL)
            if "repository" in raw
            else None,
        ),
        shape=Shape(_choice(entry["shape"], f"{where}.shape", tuple(s.value for s in Shape))),
        ranges=ranges,
        versions=_unique_strings(entry["versions"], f"{where}.versions") if "versions" in entry else (),
    )


def _reference(value: Any, where: str) -> None:
    entry = strict.obj(value, where, frozenset({"type", "url"}), frozenset({"type", "url"}))
    _choice(entry["type"], f"{where}.type", REFERENCE_TYPES)
    strict.string(entry["url"], f"{where}.url", pattern=_URL)


def _credit(value: Any, where: str) -> None:
    entry = strict.obj(value, where, frozenset({"name", "contact", "type"}), frozenset({"name"}))
    strict.string(entry["name"], f"{where}.name", empty=False)
    if "contact" in entry:
        strict.array(entry["contact"], f"{where}.contact", lambda v, w: strict.string(v, w, empty=False))
    if "type" in entry:
        _choice(entry["type"], f"{where}.type", CREDIT_TYPES)


def read_record(data: Any) -> Record:
    """A registry record, read strictly: the published schema and the rules it cannot express, or ``ValueError``."""
    top = strict.obj(data, "record", _TOP, _REQUIRED)
    if top["$schema"] != REGISTRY_RECORD_SCHEMA:
        raise ValueError(f"$schema: expected {REGISTRY_RECORD_SCHEMA}")
    strict.string(top["schema_version"], "schema_version", pattern=_VERSION)
    status = _choice(top["status"], "status", STATUSES)
    if (status == "withdrawn") != ("withdrawn" in top):
        raise ValueError("withdrawn: a withdrawn record says when, and only a withdrawn record has the field")
    if "withdrawn" in top:
        _time(top["withdrawn"], "withdrawn")
    strict.string(top["numbering_authority"], "numbering_authority", empty=False)
    summary = strict.string(top["summary"], "summary", empty=False)
    if len(summary) > 120:
        raise ValueError("summary: at most 120 characters, one line a reader can forward")
    if "details" in top:
        strict.string(top["details"], "details", empty=False)
    for key in ("aliases", "related"):
        if key in top:
            _unique_strings(top[key], key)
    weakness = _unique_strings(top["weakness"], "weakness", WEAKNESS_ID)
    if not weakness:
        raise ValueError("weakness: names at least one class")
    known = {w.id for w in weakness_list().weaknesses}
    unknown = [w for w in weakness if w not in known]
    if unknown:
        raise ValueError(f"weakness: {unknown} are not classes of the weakness list")
    if "probe" in top:
        strict.string(top["probe"], "probe", pattern=PROBE_ID)
    if "findings" in top:
        _unique_strings(top["findings"], "findings", FINDING_ID)
    affected = strict.array(top["affected"], "affected", _affected)
    if not affected:
        raise ValueError("affected: names at least one artefact")
    if "references" in top:
        strict.array(top["references"], "references", _reference)
    if "credits" in top:
        strict.array(top["credits"], "credits", _credit)
    disclosure = strict.obj(
        top["disclosure"],
        "disclosure",
        frozenset({"maintainer_notified", "maintainer_agreed_early"}),
        frozenset({"maintainer_notified"}),
    )
    notified = _time(disclosure["maintainer_notified"], "disclosure.maintainer_notified")
    agreed_early = (
        strict.boolean(disclosure["maintainer_agreed_early"], "disclosure.maintainer_agreed_early")
        if "maintainer_agreed_early" in disclosure
        else False
    )
    published = _time(top["published"], "published")
    _check_notice(published, notified, status, agreed_early)
    return Record(
        id=strict.string(top["id"], "id", pattern=RECORD_ID),
        status=status,
        published=published,
        modified=_time(top["modified"], "modified"),
        maintainer_notified=notified,
        summary=summary,
        weakness=weakness,
        affected=affected,
        submission=_read_submission(top["submission"]) if "submission" in top else None,
        score_received=_read_scored(top["score_received"], "score_received") if "score_received" in top else None,
        ground=Ground(_choice(top["ground"], "ground", tuple(g.value for g in Ground))) if "ground" in top else None,
        reproduce=_read_reproduction(top["reproduce"]) if "reproduce" in top else None,
        document=MappingProxyType(json.loads(json.dumps(top))),
    )


def _check_notice(published: datetime, notified: datetime, status: str, agreed_early: bool) -> None:
    """The notification policy: never before the maintainer was told, and 45 days after unless fixed and agreed."""
    if published < notified:
        raise ValueError("published: a record is never published before the maintainer was told")
    if published < notified + timedelta(days=NOTICE_DAYS) and not (status == "fixed" and agreed_early):
        raise ValueError(
            f"published: {NOTICE_DAYS} days must pass after the maintainer was told, unless the defect is fixed "
            "and the maintainer agreed to earlier publication"
        )


@cache
def registry_record_schema() -> dict[str, Any]:
    """The JSON Schema published at ``https://bohrin.com/schema/registry-record/v1``."""
    loaded: dict[str, Any] = json.loads(files("bohrin.registry").joinpath("record.v1.json").read_text("utf-8"))
    return loaded


__all__ = [
    "NOTICE_DAYS",
    "REGISTRY_RECORD_SCHEMA",
    "Affected",
    "Artifact",
    "Record",
    "read_record",
    "registry_record_schema",
]
