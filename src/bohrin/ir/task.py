"""The canonical representation of a task, a candidate and a verdict.

Every definition in Bohrin is written against these types and never against a specific
environment format, which is what keeps the definitions portable across formats.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar


class Ground(StrEnum):
    """How a candidate's incorrectness was established.

    The critical property is that every ground is established **independently of the
    verifier under audit**. A candidate that passes because the verifier is lenient tells
    us nothing about whether the candidate is wrong; that has to be settled separately, or
    Bohrin ends up reporting a correct verifier as broken.
    """

    #: The candidate provably does not do the work: no answer produced, body emptied,
    #: required side effect removed. Wrongness holds by construction.
    STRUCTURAL = "structural"

    #: The candidate differs observably from a known-good reference. Strongest ground,
    #: but requires the taskset to supply a reference.
    DIFFERENTIAL = "differential"

    #: The candidate violates an invariant the taskset itself declares, independently of
    #: the reward function being probed.
    INVARIANT = "invariant"


class Shape(StrEnum):
    """How a grader is called, which decides what a probe against it means.

    ``numeric``, ``proof`` and ``query`` are defined so the weakness list is complete; no
    probe targets them yet.
    """

    #: (task, source) -> reward, with tests run in-process or in a subprocess.
    PROGRAM = "program"
    #: A program run on inputs, with a checker comparing its output.
    IO = "io"
    #: A repository plus a patch, judged by a test command.
    WORKSPACE = "workspace"
    #: The agent acts in a container, and a script there writes the reward.
    CONTAINER = "container"
    #: A change in a repository with a claim of success, read from version history.
    HISTORY = "history"
    #: A program whose output is compared within a numeric tolerance.
    NUMERIC = "numeric"
    #: A proof checked by a proof assistant.
    PROOF = "proof"
    #: A database query checked by executing it.
    QUERY = "query"


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a candidate came from, so a finding can be reproduced and argued with."""

    operator: str
    #: What the candidate was derived from — "reference", "prompt", or "constant".
    base: str
    #: One line a human can read: what was changed and why that makes it wrong.
    detail: str


@dataclass(frozen=True, slots=True)
class Source:
    """A submission that is program text: a solution, a module, a reply."""

    kind: ClassVar[str] = "source"

    text: str

    def __post_init__(self) -> None:
        _unicode(self.text, "source text")

    @property
    def key(self) -> str:
        """What makes two submissions the same one: surrounding whitespace is not part of a program."""
        return f"source:{self.text.strip()}"


#: A parameter placeholder in a workspace path, such as ``{test_root}``.
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True, slots=True)
class Workspace:
    """A submission that is a set of file changes, and commands, applied to a repository or container.

    ``files`` maps a path to its new content, or to ``None`` to delete it. Paths are relative
    to the root of whatever the submission is applied to, and may never leave it.

    **A workspace is a template, never an instantiation.** A path may name a parameter, such
    as ``{test_root}/conftest.py``, and every parameter it names is declared in
    ``parameters``. Filling a parameter in needs knowledge of one particular environment (its
    test root, its reward path, its parser), so nothing in this library does it: the template
    is the same for every environment, which is what lets anyone read it and check it.
    """

    kind: ClassVar[str] = "workspace"

    files: Mapping[str, str | None] = field(default_factory=dict)
    commands: tuple[str, ...] = ()
    parameters: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for path, content in self.files.items():
            _unicode(path, "a workspace path")
            if content is not None:
                _unicode(content, f"the content of {path!r}")
        for command in self.commands:
            _unicode(command, "a workspace command")
        for name in self.parameters:
            if not _IDENTIFIER.fullmatch(name):
                raise ValueError(f"parameter {name!r} is not an identifier")
        if len(set(self.parameters)) != len(self.parameters):
            raise ValueError(f"parameters repeat: {self.parameters}")
        for path in self.files:
            _check_path(path, self.parameters)
        # Frozen means frozen: a caller's dict must not be able to change a candidate after the
        # battery has checked it. Sorted, so equal workspaces render identically.
        object.__setattr__(self, "files", MappingProxyType(dict(sorted(self.files.items()))))

    def __hash__(self) -> int:
        return hash(self.key)

    @property
    def key(self) -> str:
        """A canonical rendering: two workspaces with the same key are the same submission."""
        body = {"files": dict(self.files), "commands": list(self.commands), "parameters": list(self.parameters)}
        return "workspace:" + json.dumps(body, sort_keys=True)


#: A Windows drive prefix, such as ``C:``. A path starting with one is not relative to the root.
_DRIVE = re.compile(r"[A-Za-z]:")


def _unicode(text: str, where: str) -> None:
    """Refuse text that cannot be written as UTF-8, such as a lone surrogate, where it enters."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{where} is not valid Unicode: {exc.reason} at position {exc.start}") from exc


def _check_path(path: str, parameters: tuple[str, ...]) -> None:
    """Refuse a path that is empty, absolute, escapes the root, or names an undeclared parameter."""
    if not path or path.startswith("/") or "\\" in path:
        raise ValueError(f"workspace path {path!r} must be relative, with forward slashes")
    if _DRIVE.match(path):
        raise ValueError(f"workspace path {path!r} starts with a drive letter, so it is not relative")
    if any(part in ("", ".", "..") for part in path.split("/")):
        raise ValueError(f"workspace path {path!r} has an empty, '.' or '..' segment")
    undeclared = sorted(set(_PLACEHOLDER.findall(path)) - set(parameters))
    if undeclared:
        raise ValueError(f"workspace path {path!r} names undeclared parameters {undeclared}")


#: A submission: program text, or changes to a workspace.
Payload = Source | Workspace


@dataclass(frozen=True, slots=True)
class Candidate:
    """A submission Bohrin constructed, carrying a claim about its own correctness."""

    payload: Payload
    provenance: Provenance

    #: How wrongness was established, or None when it was not. This field is load-bearing:
    #: only a candidate with a ground may ever be reported as an exploit.
    ground: Ground | None = None

    @property
    def known_wrong(self) -> bool:
        """True only when incorrectness was established independently of the verifier."""
        return self.ground is not None


@dataclass(frozen=True, slots=True)
class Task:
    """One unit of work with a verifier attached."""

    id: str
    prompt: str

    #: A known-good solution, when the taskset provides one. Without it, the differential
    #: ground is unavailable and only structural operators apply.
    reference: str | None = None

    #: Names of the reward functions this task scores. Length is informative: a single
    #: reward function is the common case in practice.
    reward_fns: tuple[str, ...] = ()

    metadata: Mapping[str, Any] = field(default_factory=dict)

    #: How this task's grader is called, which decides which operators apply to it.
    shape: Shape = Shape.PROGRAM


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the verifier said about a candidate."""

    reward: float
    passed: bool
    per_fn: Mapping[str, float] = field(default_factory=dict)
    raw: Mapping[str, Any] = field(default_factory=dict)
    #: The reward came out *above* full marks as the rubric declares them. ``passed`` means
    #: "reached full marks", and full marks are read from the rubric's weights, which assume
    #: each reward function returns 0 to 1. A rubric paying past that -- a sum of 0-3
    #: criteria, a mean of 1-5 ratings -- has a scale Bohrin does not know, so on it
    #: ``passed`` says only "scored at least 1", not "scored like a correct reply".
    scale_exceeded: bool = False


__all__ = ["Candidate", "Ground", "Payload", "Provenance", "Shape", "Source", "Task", "Verdict", "Workspace"]
