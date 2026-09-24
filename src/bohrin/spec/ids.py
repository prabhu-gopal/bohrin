"""The identifier formats every Bohrin artefact uses.

Identifiers outlive every other design choice, so they follow conventions the security field
has already proven: CWE for weakness classes, CVE and OSV for records, CodeQL for query IDs,
git and SARIF for content-derived fingerprints, JSON Schema for versioned schema URIs.

* Weakness class: ``BGW-<number>``, for example ``BGW-108``.
* Registry record: ``BVR-<year>-<five or more digits>``, for example ``BVR-2026-00042``.
* Probe: ``<namespace>/<slug>@<major>``, for example ``bohrin/pytest-report-patch@1``.
* Finding: ``BF-<ten Crockford base32 characters>``, for example ``BF-7K3Q9D2M1X``.
* Schema: ``https://bohrin.com/schema/<name>/v<major>``.
* Conformance level: ``BCL-1`` to ``BCL-4``.

Rules:

* A weakness number carries no meaning and is never reused; a retired class keeps its number.
* A record's year is the year the ID was assigned, and its sequence grows without limit.
* A probe's major version changes when what the probe tries changes. Third parties publish
  probes under their own namespace.
* Crockford base32 has no ``I``, ``L``, ``O`` or ``U``, so a finding ID cannot be misread.
"""

from __future__ import annotations

import re

WEAKNESS_ID = re.compile(r"BGW-[1-9][0-9]*")
RECORD_ID = re.compile(r"BVR-[0-9]{4}-[0-9]{5,}")
PROBE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*@[1-9][0-9]*")
FINDING_ID = re.compile(r"BF-[0-9A-HJKMNP-TV-Z]{10}")
SCHEMA_ID = re.compile(r"https://bohrin\.com/schema/[a-z0-9]+(?:-[a-z0-9]+)*/v[1-9][0-9]*")
CONFORMANCE_LEVEL = re.compile(r"BCL-[1-4]")


def is_weakness_id(text: str) -> bool:
    """Whether ``text`` is a well-formed weakness class ID, such as ``BGW-108``."""
    return WEAKNESS_ID.fullmatch(text) is not None


def is_record_id(text: str) -> bool:
    """Whether ``text`` is a well-formed registry record ID, such as ``BVR-2026-00042``."""
    return RECORD_ID.fullmatch(text) is not None


def is_probe_id(text: str) -> bool:
    """Whether ``text`` is a well-formed probe ID, such as ``bohrin/pytest-report-patch@1``."""
    return PROBE_ID.fullmatch(text) is not None


def is_finding_id(text: str) -> bool:
    """Whether ``text`` is a well-formed finding ID, such as ``BF-7K3Q9D2M1X``."""
    return FINDING_ID.fullmatch(text) is not None


def is_schema_id(text: str) -> bool:
    """Whether ``text`` is a well-formed schema URI, such as ``https://bohrin.com/schema/finding/v1``."""
    return SCHEMA_ID.fullmatch(text) is not None


def is_conformance_level(text: str) -> bool:
    """Whether ``text`` is a conformance level, ``BCL-1`` to ``BCL-4``."""
    return CONFORMANCE_LEVEL.fullmatch(text) is not None


def weakness_number(weakness_id: str) -> int:
    """The number of a weakness ID, for sorting: ``BGW-108`` is ``108``."""
    if not is_weakness_id(weakness_id):
        raise ValueError(f"not a weakness ID: {weakness_id!r}")
    return int(weakness_id.removeprefix("BGW-"))


__all__ = [
    "CONFORMANCE_LEVEL",
    "FINDING_ID",
    "PROBE_ID",
    "RECORD_ID",
    "SCHEMA_ID",
    "WEAKNESS_ID",
    "is_conformance_level",
    "is_finding_id",
    "is_probe_id",
    "is_record_id",
    "is_schema_id",
    "is_weakness_id",
    "weakness_number",
]
