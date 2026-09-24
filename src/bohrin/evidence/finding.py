"""The finding record: one result, in the form every report, registry record and certificate uses.

Published as ``https://bohrin.com/schema/finding/v1`` (``finding.v1.json`` in this package).
A record never carries the submission itself, only its digests: the exact submission travels in
the reproduction script, so a record is small and safe to pass around.

**The rules of evidence are enforced when a record is made**, not left to whoever renders it. A
record that claims more than its evidence supports raises instead of existing:

* a proven finding has a ground established without the grader (I1), a grader that paid full
  marks, a baseline that passed (I4) and a reproduction script (I7);
* a proven finding on a differential ground carries a differentiating input or observation (I8);
* a differentiating observation proves nothing unless the reference and at least three
  presumed-correct solutions pass it and the submission fails it (I12), and a finding proven that
  way is always ``proven-experimental`` until the method's error rate has been measured.

A finding's ID is derived from what was tried and where, never from when or on which machine, so
the same defect gets the same ID on every run.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar

from bohrin.ir.task import Ground, Payload, Shape, Source
from bohrin.spec.ids import is_finding_id, is_probe_id, is_weakness_id

SCHEMA = "https://bohrin.com/schema/finding/v1"

#: How far a finding's evidence goes. Only ``proven`` counts in a headline number.
LEVELS: Mapping[str, str] = MappingProxyType(
    {
        "proven": "grounded, paid for by the grader, baseline passing, re-created by its reproduction script",
        "proven-experimental": "proven, by a probe or a method whose error rate has not yet been measured",
        "suspected": "a structural risk read from the harness, with no working exploit",
        "lead": "accepted by the grader, but its wrongness was not established",
        "observation": "a fact a correct grader or an honest agent could also produce",
        "excluded": "could not be measured soundly, and left out of every rate",
    }
)
PROVEN = ("proven", "proven-experimental")

#: Crockford's base32 alphabet: no I, L, O or U, so an ID cannot be misread or misspelt rudely.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
#: Crockford decoding: lower case is accepted, and I, L and O are read as the digits they resemble.
_CROCKFORD_READ = str.maketrans("ILO", "110")


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Submission:
    """What was submitted, as digests. Built from a payload with :meth:`of`."""

    kind: str
    #: For a source submission: the digest of its text.
    sha256: str | None = None
    #: For a workspace: path -> digest of its new content, or None for a deletion.
    files: Mapping[str, str | None] = field(default_factory=dict)
    commands: tuple[str, ...] = ()
    parameters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in ("source", "workspace"):
            raise ValueError(f"unknown submission kind {self.kind!r}")
        if (self.kind == "source") != (self.sha256 is not None):
            raise ValueError("a source submission carries a digest, and only a source submission does")
        object.__setattr__(self, "files", MappingProxyType(dict(sorted(self.files.items()))))

    def __hash__(self) -> int:
        return hash(json.dumps(self.to_json(), sort_keys=True))

    @classmethod
    def of(cls, payload: Payload) -> Submission:
        """The digests of a submission: what a finding records instead of its content."""
        if isinstance(payload, Source):
            return cls(kind="source", sha256=_sha256(payload.text))
        return cls(
            kind="workspace",
            files={path: None if content is None else _sha256(content) for path, content in payload.files.items()},
            commands=payload.commands,
            parameters=payload.parameters,
        )

    def to_json(self) -> dict[str, Any]:
        """The submission as it appears in a finding record."""
        if self.kind == "source":
            return {"kind": "source", "sha256": self.sha256}
        return {
            "kind": "workspace",
            "files": dict(self.files),
            "commands": list(self.commands),
            "parameters": list(self.parameters),
        }


def finding_id(probe: str, task_id: str, grader_fingerprint: str, submission: Submission) -> str:
    """The ``BF-`` ID of a finding: the same inputs give the same ID on every run and machine.

    ``grader_fingerprint`` identifies the grader under audit, such as a digest of its source; it is
    supplied by whatever ran the grader. Fifty bits of a SHA-256 over the four inputs, written as
    ten Crockford base32 characters.
    """
    canonical = json.dumps([probe, task_id, grader_fingerprint, submission.to_json()], sort_keys=True)
    bits = int.from_bytes(hashlib.sha256(canonical.encode("utf-8")).digest()[:7], "big") >> 6
    return "BF-" + "".join(_CROCKFORD[(bits >> shift) & 31] for shift in range(45, -1, -5))


def normalise_finding_id(text: str) -> str:
    """A finding ID as a person might type it, read the way Crockford base32 is read.

    Case is ignored, ``I`` and ``L`` are read as ``1`` and ``O`` as ``0``, and hyphens after the
    prefix are ignored. Raises ``ValueError`` if what remains is not a finding ID.
    """
    body = text.strip().upper()
    if not body.startswith("BF-"):
        raise ValueError(f"not a finding ID: {text!r}")
    normalised = "BF-" + body[3:].replace("-", "").translate(_CROCKFORD_READ)
    if not is_finding_id(normalised):
        raise ValueError(f"not a finding ID: {text!r}")
    return normalised


@dataclass(frozen=True, slots=True)
class Scored:
    """What the grader under audit did with the submission."""

    reward: float
    passed: bool


@dataclass(frozen=True, slots=True)
class Reproduction:
    """The standalone script that re-creates the finding, by file name and digest."""

    script: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DifferentiatingInput:
    """An input on which the reference and the submission produce different outputs.

    Anyone can check it by running the two programs. It proves a program wrong (BGW-104, BGW-119)
    without asking the grader under audit.
    """

    input: str
    reference_output: str
    submission_output: str

    def __post_init__(self) -> None:
        if self.reference_output == self.submission_output:
            raise ValueError("a differentiating input must produce different outputs")


@dataclass(frozen=True, slots=True)
class DifferentiatingObservation:
    """A read-only check of an end state, tied to a sentence of the task, that the submission fails.

    For tasks whose result is the state of an environment rather than a program's output. It
    proves something only when it is not too narrow: the reference's end state and every available
    presumed-correct end state pass it, and there are at least three of those (invariant I12).
    Presumed-correct solutions can only ever veto a finding this way; they are never the reason
    one is made.
    """

    #: The sentence of the task text the observation checks, quoted exactly.
    requirement: str
    #: The read-only command run on the end state.
    observation: str
    reference_passed: bool
    presumed_correct_passed: tuple[bool, ...]
    submission_passed: bool

    #: Fewer presumed-correct end states than this, and the observation cannot rule out being too narrow.
    MIN_PRESUMED_CORRECT: ClassVar[int] = 3

    def __post_init__(self) -> None:
        if not self.requirement.strip() or not self.observation.strip():
            raise ValueError("an observation must quote its requirement and name its check")

    @property
    def proves(self) -> bool:
        """Whether the observation can prove anything: never too narrow, and failed by the submission."""
        return (
            self.reference_passed
            and len(self.presumed_correct_passed) >= self.MIN_PRESUMED_CORRECT
            and all(self.presumed_correct_passed)
            and not self.submission_passed
        )


@dataclass(frozen=True, slots=True)
class Run:
    """The conditions a result was produced under, because resource settings alone move scores."""

    tool: str
    tool_version: str
    environment_digest: str | None = None
    #: CPU, memory, timeout, network egress and the like, as the tool reports them.
    conditions: Mapping[str, str | int | float | bool] = field(default_factory=dict)
    #: A file holding signed provenance for the run, if there is one.
    provenance: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "conditions", MappingProxyType(dict(self.conditions)))


@dataclass(frozen=True, slots=True)
class Finding:
    """One result about a grader, with exactly the evidence it has and no more."""

    id: str
    weakness: str
    probe: str
    level: str
    task_id: str
    shape: Shape
    battery: int
    submission: Submission | None = None
    ground: Ground | None = None
    verdict: Scored | None = None
    #: Whether the task's own reference passed its grader: the baseline every finding needs.
    baseline_passed: bool | None = None
    reproduce: Reproduction | None = None
    differentiating_input: DifferentiatingInput | None = None
    differentiating_observation: DifferentiatingObservation | None = None
    run: Run | None = None
    #: Static guidance from the weakness list, never a fix written for this grader.
    fix: str = ""
    #: Why a lead was not proven, or why an excluded result could not be measured.
    reason: str = ""

    def __post_init__(self) -> None:
        if not is_finding_id(self.id):
            raise ValueError(f"malformed finding ID {self.id!r}")
        if not is_weakness_id(self.weakness):
            raise ValueError(f"malformed weakness ID {self.weakness!r}")
        if not is_probe_id(self.probe):
            raise ValueError(f"malformed probe ID {self.probe!r}")
        if self.level not in LEVELS:
            raise ValueError(f"level must be one of {sorted(LEVELS)}")
        if self.battery < 1:
            raise ValueError("battery must be a positive integer")
        if self.level in PROVEN:
            self._check_proven()
        if self.level in ("lead", "excluded") and not self.reason.strip():
            raise ValueError(f"a {self.level} finding states why it is not proven")

    def _check_proven(self) -> None:
        missing = [
            name
            for name, value in (
                ("submission", self.submission),
                ("ground", self.ground),
                ("verdict", self.verdict),
                ("reproduce", self.reproduce),
            )
            if value is None
        ]
        if missing:
            raise ValueError(f"a proven finding needs {', '.join(missing)}")
        if self.verdict is not None and not self.verdict.passed:
            raise ValueError("a proven finding needs a grader that paid full marks")
        if self.baseline_passed is not True:
            raise ValueError("a proven finding needs a baseline that passed its own grader")
        if (
            self.ground is Ground.DIFFERENTIAL
            and self.differentiating_input is None
            and self.differentiating_observation is None
        ):
            raise ValueError("a differential ground is proven by a differentiating input or observation")
        observation = self.differentiating_observation
        if observation is not None:
            if not observation.proves:
                raise ValueError(
                    "a differentiating observation proves nothing unless the reference and at least "
                    f"{DifferentiatingObservation.MIN_PRESUMED_CORRECT} presumed-correct solutions pass it "
                    "and the submission fails it"
                )
            if self.level != "proven-experimental":
                raise ValueError("a finding proven by a differentiating observation is proven-experimental")

    def to_json(self) -> dict[str, Any]:
        """The record as JSON, conforming to ``finding.v1.json``. Absent evidence is omitted."""
        out: dict[str, Any] = {
            "$schema": SCHEMA,
            "id": self.id,
            "weakness": self.weakness,
            "probe": self.probe,
            "level": self.level,
            "task": {"id": self.task_id, "shape": self.shape.value},
            "battery": self.battery,
        }
        if self.submission is not None:
            out["submission"] = self.submission.to_json()
        if self.ground is not None:
            out["ground"] = self.ground.value
        if self.verdict is not None:
            out["verdict"] = {"reward": self.verdict.reward, "passed": self.verdict.passed}
        if self.baseline_passed is not None:
            out["baseline"] = {"passed": self.baseline_passed}
        if self.reproduce is not None:
            out["reproduce"] = {"script": self.reproduce.script, "sha256": self.reproduce.sha256}
        if self.differentiating_input is not None:
            d = self.differentiating_input
            out["differentiating_input"] = {
                "input": d.input,
                "reference_output": d.reference_output,
                "submission_output": d.submission_output,
            }
        if self.differentiating_observation is not None:
            o = self.differentiating_observation
            out["differentiating_observation"] = {
                "requirement": o.requirement,
                "observation": o.observation,
                "reference_passed": o.reference_passed,
                "presumed_correct_passed": list(o.presumed_correct_passed),
                "submission_passed": o.submission_passed,
            }
        if self.run is not None:
            run: dict[str, Any] = {"tool": self.run.tool, "tool_version": self.run.tool_version}
            if self.run.environment_digest is not None:
                run["environment_digest"] = self.run.environment_digest
            if self.run.conditions:
                run["conditions"] = dict(self.run.conditions)
            if self.run.provenance is not None:
                run["provenance"] = self.run.provenance
            out["run"] = run
        if self.fix:
            out["fix"] = self.fix
        if self.reason:
            out["reason"] = self.reason
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Finding:
        """Read a record back. The same rules apply: a record claiming too much raises.

        Unknown fields are refused at every level, as the published schema refuses them: a field
        this version does not define is a claim this version cannot check.
        """
        if data.get("$schema") != SCHEMA:
            raise ValueError(f"not a {SCHEMA} record")
        _only(data, _FIELDS, "finding")
        for key, allowed in _NESTED.items():
            if isinstance(data.get(key), Mapping):
                _only(data[key], allowed, key)
        sub = data.get("submission")
        submission = None
        if sub is not None:
            submission = Submission(
                kind=sub["kind"],
                sha256=sub.get("sha256"),
                files=sub.get("files", {}),
                commands=tuple(sub.get("commands", ())),
                parameters=tuple(sub.get("parameters", ())),
            )
        verdict = data.get("verdict")
        reproduce = data.get("reproduce")
        dinput = data.get("differentiating_input")
        dobs = data.get("differentiating_observation")
        run = data.get("run")
        return cls(
            id=data["id"],
            weakness=data["weakness"],
            probe=data["probe"],
            level=data["level"],
            task_id=data["task"]["id"],
            shape=Shape(data["task"]["shape"]),
            battery=data["battery"],
            submission=submission,
            ground=Ground(data["ground"]) if "ground" in data else None,
            verdict=Scored(reward=verdict["reward"], passed=verdict["passed"]) if verdict else None,
            baseline_passed=data["baseline"]["passed"] if "baseline" in data else None,
            reproduce=Reproduction(script=reproduce["script"], sha256=reproduce["sha256"]) if reproduce else None,
            differentiating_input=DifferentiatingInput(**dinput) if dinput else None,
            differentiating_observation=(
                DifferentiatingObservation(
                    requirement=dobs["requirement"],
                    observation=dobs["observation"],
                    reference_passed=dobs["reference_passed"],
                    presumed_correct_passed=tuple(dobs["presumed_correct_passed"]),
                    submission_passed=dobs["submission_passed"],
                )
                if dobs
                else None
            ),
            run=(
                Run(
                    tool=run["tool"],
                    tool_version=run["tool_version"],
                    environment_digest=run.get("environment_digest"),
                    conditions=run.get("conditions", {}),
                    provenance=run.get("provenance"),
                )
                if run
                else None
            ),
            fix=data.get("fix", ""),
            reason=data.get("reason", ""),
        )


_FIELDS = frozenset(
    {
        "$schema", "id", "weakness", "probe", "level", "task", "battery", "submission", "ground", "verdict",
        "baseline", "reproduce", "differentiating_input", "differentiating_observation", "run", "fix", "reason",
    }
)  # fmt: skip
_NESTED: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "task": frozenset({"id", "shape"}),
        "submission": frozenset({"kind", "sha256", "files", "commands", "parameters"}),
        "verdict": frozenset({"reward", "passed"}),
        "baseline": frozenset({"passed"}),
        "reproduce": frozenset({"script", "sha256"}),
        "differentiating_input": frozenset({"input", "reference_output", "submission_output"}),
        "differentiating_observation": frozenset(
            {"requirement", "observation", "reference_passed", "presumed_correct_passed", "submission_passed"}
        ),
        "run": frozenset({"tool", "tool_version", "environment_digest", "conditions", "provenance"}),
    }
)


def _only(data: Mapping[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{where}: fields not defined by {SCHEMA}: {unknown}")


__all__ = [
    "LEVELS",
    "PROVEN",
    "SCHEMA",
    "DifferentiatingInput",
    "DifferentiatingObservation",
    "Finding",
    "Reproduction",
    "Run",
    "Scored",
    "Submission",
    "finding_id",
    "normalise_finding_id",
]
