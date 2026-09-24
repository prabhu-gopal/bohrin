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
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar

from bohrin.evidence import _strict as strict
from bohrin.evidence.canonical import canonical_json
from bohrin.ir.task import Ground, Payload, Shape, Source
from bohrin.spec.ids import FINDING_ID, PROBE_ID, WEAKNESS_ID, is_finding_id, is_probe_id, is_weakness_id

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


#: A parameter a workspace template names, such as ``test_root``.
_PARAMETER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
#: Text with at least one character that is not whitespace.
_MEANINGFUL = re.compile(r"(?s).*\S.*")


def _meaningful(text: str, where: str) -> None:
    if _MEANINGFUL.fullmatch(text) is None:
        raise ValueError(f"{where}: must say something, not only whitespace")


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
        if self.sha256 is not None:
            strict.string(self.sha256, "submission.sha256", pattern=strict.DIGEST)
        for path, digest in self.files.items():
            strict.string(path, "submission.files", empty=False)
            if digest is not None:
                strict.string(digest, f"submission.files[{path!r}]", pattern=strict.DIGEST)
        for command in self.commands:
            strict.string(command, "submission.commands")
        for name in self.parameters:
            strict.string(name, "submission.parameters", pattern=_PARAMETER)
        object.__setattr__(self, "files", MappingProxyType(dict(sorted(self.files.items()))))

    def __hash__(self) -> int:
        return hash(canonical_json(self.to_json()))

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
    supplied by whatever ran the grader. The ID is the first fifty bits of the SHA-256 of the
    RFC 8785 canonical JSON of ``[probe, task_id, grader_fingerprint, submission]``, written as ten
    Crockford base32 characters, so anyone can recompute it in any language.
    """
    canonical = canonical_json([probe, task_id, grader_fingerprint, submission.to_json()])
    bits = int.from_bytes(hashlib.sha256(canonical).digest()[:7], "big") >> 6
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

    def __post_init__(self) -> None:
        strict.number(self.reward, "reward")
        strict.boolean(self.passed, "passed")


@dataclass(frozen=True, slots=True)
class Reproduction:
    """The standalone script that re-creates the finding, by file name and digest."""

    script: str
    sha256: str

    def __post_init__(self) -> None:
        strict.string(self.script, "reproduce.script", empty=False)
        strict.string(self.sha256, "reproduce.sha256", pattern=strict.DIGEST)


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
        for name in ("input", "reference_output", "submission_output"):
            strict.string(getattr(self, name), f"differentiating_input.{name}")
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
        _meaningful(strict.string(self.requirement, "requirement"), "differentiating_observation.requirement")
        _meaningful(strict.string(self.observation, "observation"), "differentiating_observation.observation")
        strict.boolean(self.reference_passed, "reference_passed")
        strict.boolean(self.submission_passed, "submission_passed")
        for passed in self.presumed_correct_passed:
            strict.boolean(passed, "presumed_correct_passed")

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
        strict.string(self.tool, "run.tool", empty=False)
        strict.string(self.tool_version, "run.tool_version", empty=False)
        for name in ("environment_digest", "provenance"):
            if getattr(self, name) is not None:
                strict.string(getattr(self, name), f"run.{name}")
        for key, value in self.conditions.items():
            where = f"run.conditions[{key!r}]"
            if isinstance(value, bool | str):
                continue
            strict.number(value, where)
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
        strict.string(self.task_id, "task.id", empty=False)
        Shape(self.shape)
        strict.integer(self.battery, "battery", minimum=1)
        if self.ground is not None:
            Ground(self.ground)
        if self.baseline_passed is not None:
            strict.boolean(self.baseline_passed, "baseline.passed")
        strict.string(self.fix, "fix")
        strict.string(self.reason, "reason")
        if self.level in PROVEN:
            self._check_proven()
        if self.level in ("lead", "excluded"):
            _meaningful(self.reason, f"a {self.level} finding states why it is not proven: reason")

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
    def from_json(cls, data: Any) -> Finding:
        """Read a record back, refusing anything the published schema refuses.

        Every field must be exactly the type the schema gives it: ``"false"`` is not false, ``null``
        is not an absent field, and a field this version does not define is a claim this version
        cannot check. Then the rules of evidence apply as for a record made in Python.
        """
        record = strict.obj(
            data, "finding", _FIELDS, frozenset({"$schema", "id", "weakness", "probe", "level", "task", "battery"})
        )
        if record["$schema"] != SCHEMA:
            raise ValueError(f"not a {SCHEMA} record")
        task = strict.obj(record["task"], "task", frozenset({"id", "shape"}), frozenset({"id", "shape"}))
        return cls(
            id=strict.string(record["id"], "id", pattern=FINDING_ID),
            weakness=strict.string(record["weakness"], "weakness", pattern=WEAKNESS_ID),
            probe=strict.string(record["probe"], "probe", pattern=PROBE_ID),
            level=strict.string(record["level"], "level"),
            task_id=strict.string(task["id"], "task.id", empty=False),
            shape=Shape(strict.string(task["shape"], "task.shape")),
            battery=strict.integer(record["battery"], "battery", minimum=1),
            submission=_read_submission(record["submission"]) if "submission" in record else None,
            ground=Ground(strict.string(record["ground"], "ground")) if "ground" in record else None,
            verdict=_read_scored(record["verdict"], "verdict") if "verdict" in record else None,
            baseline_passed=(
                strict.boolean(
                    strict.obj(record["baseline"], "baseline", _ONLY_PASSED, _ONLY_PASSED)["passed"], "baseline.passed"
                )
                if "baseline" in record
                else None
            ),
            reproduce=_read_reproduction(record["reproduce"]) if "reproduce" in record else None,
            differentiating_input=_read_input(record["differentiating_input"])
            if "differentiating_input" in record
            else None,
            differentiating_observation=(
                _read_observation(record["differentiating_observation"])
                if "differentiating_observation" in record
                else None
            ),
            run=_read_run(record["run"]) if "run" in record else None,
            fix=strict.string(record.get("fix", ""), "fix"),
            reason=strict.string(record.get("reason", ""), "reason"),
        )


_FIELDS = frozenset(
    {
        "$schema", "id", "weakness", "probe", "level", "task", "battery", "submission", "ground", "verdict",
        "baseline", "reproduce", "differentiating_input", "differentiating_observation", "run", "fix", "reason",
    }
)  # fmt: skip
_ONLY_PASSED = frozenset({"passed"})
_SCORED = frozenset({"reward", "passed"})


def _read_submission(value: Any) -> Submission:
    either = frozenset({"kind", "sha256", "files", "commands", "parameters"})
    kind = strict.string(strict.obj(value, "submission", either, frozenset({"kind"}))["kind"], "submission.kind")
    if kind == "source":
        sub = strict.obj(value, "submission", frozenset({"kind", "sha256"}), frozenset({"kind", "sha256"}))
        return Submission(
            kind="source", sha256=strict.string(sub["sha256"], "submission.sha256", pattern=strict.DIGEST)
        )
    if kind != "workspace":
        raise ValueError(f"unknown submission kind {kind!r}")
    fields = frozenset({"kind", "files", "commands", "parameters"})
    sub = strict.obj(value, "submission", fields, fields)
    files = strict.obj(
        sub["files"], "submission.files", frozenset(sub["files"]) if isinstance(sub["files"], dict) else frozenset()
    )
    return Submission(
        kind="workspace",
        files={
            path: None
            if digest is None
            else strict.string(digest, f"submission.files[{path!r}]", pattern=strict.DIGEST)
            for path, digest in files.items()
        },
        commands=strict.array(sub["commands"], "submission.commands", strict.string),
        parameters=strict.array(
            sub["parameters"], "submission.parameters", lambda v, w: strict.string(v, w, pattern=_PARAMETER)
        ),
    )


def _read_scored(value: Any, where: str) -> Scored:
    scored = strict.obj(value, where, _SCORED, _SCORED)
    return Scored(
        reward=strict.number(scored["reward"], f"{where}.reward"),
        passed=strict.boolean(scored["passed"], f"{where}.passed"),
    )


def _read_reproduction(value: Any) -> Reproduction:
    fields = frozenset({"script", "sha256"})
    reproduce = strict.obj(value, "reproduce", fields, fields)
    return Reproduction(
        script=strict.string(reproduce["script"], "reproduce.script", empty=False),
        sha256=strict.string(reproduce["sha256"], "reproduce.sha256", pattern=strict.DIGEST),
    )


def _read_input(value: Any) -> DifferentiatingInput:
    fields = frozenset({"input", "reference_output", "submission_output"})
    d = strict.obj(value, "differentiating_input", fields, fields)
    return DifferentiatingInput(
        **{name: strict.string(d[name], f"differentiating_input.{name}") for name in sorted(fields)}
    )


def _read_observation(value: Any) -> DifferentiatingObservation:
    fields = frozenset(
        {"requirement", "observation", "reference_passed", "presumed_correct_passed", "submission_passed"}
    )
    o = strict.obj(value, "differentiating_observation", fields, fields)
    return DifferentiatingObservation(
        requirement=strict.string(o["requirement"], "requirement", empty=False),
        observation=strict.string(o["observation"], "observation", empty=False),
        reference_passed=strict.boolean(o["reference_passed"], "reference_passed"),
        presumed_correct_passed=strict.array(o["presumed_correct_passed"], "presumed_correct_passed", strict.boolean),
        submission_passed=strict.boolean(o["submission_passed"], "submission_passed"),
    )


def _read_run(value: Any) -> Run:
    fields = frozenset({"tool", "tool_version", "environment_digest", "conditions", "provenance"})
    run = strict.obj(value, "run", fields, frozenset({"tool", "tool_version"}))
    conditions = strict.obj(run.get("conditions", {}), "run.conditions", frozenset(run.get("conditions", {}) or {}))
    for key, item in conditions.items():
        if not isinstance(item, bool | str):
            strict.number(item, f"run.conditions[{key!r}]")
    return Run(
        tool=strict.string(run["tool"], "run.tool", empty=False),
        tool_version=strict.string(run["tool_version"], "run.tool_version", empty=False),
        environment_digest=strict.string(run["environment_digest"], "run.environment_digest")
        if "environment_digest" in run
        else None,
        conditions=dict(conditions),
        provenance=strict.string(run["provenance"], "run.provenance") if "provenance" in run else None,
    )


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
