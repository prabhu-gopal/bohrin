"""What boundary, if any, stands between a verifier's code and the host.

Bohrin executes code it did not write. Even on the offline path — where a candidate is
scored by invoking the task's reward functions directly — that reward function is the
taskset author's arbitrary Python, running inside the Bohrin interpreter. There is no
boundary there at all, and pretending otherwise would be the same kind of dishonesty this
codebase refuses everywhere else.

This module does not provide a sandbox. It **classifies** what the caller already has,
refuses to run unshielded work unless that is explicitly accepted, and records the level in
the report — because how an audit was executed is part of its evidence, and a certificate
that cannot say how it was produced is worth very little.

**Naming is deliberate.** Published guidance is blunt that process-level limits are not a
security boundary: they prevent denial of service, not escape, because the code still makes
syscalls to the same kernel. Seccomp and namespaces share that weakness, and Python's
introspection offers many routes out of an in-process restriction. So the level below a
container is called ``SUBPROCESS`` and described as blast-radius containment, never as a
sandbox.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path


class Isolation(IntEnum):
    """How much stands between a verifier's code and the host, weakest first.

    Ordered so policy can be expressed as a comparison.
    """

    #: Executed inside the Bohrin interpreter. No boundary whatsoever.
    NONE = 0

    #: A separate process with resource ceilings where the platform enforces them.
    #: Contains accidents — runaway loops, memory growth — and nothing else. An adversary
    #: is not contained by this.
    SUBPROCESS = 1

    #: A container. A real boundary against accidents and casual misbehaviour, but it
    #: shares the host kernel, so a kernel bug defeats it.
    CONTAINER = 2

    #: Hardware virtualisation. The only level appropriate for genuinely adversarial code.
    VM = 3

    @property
    def label(self) -> str:
        return {
            Isolation.NONE: "none (in-process)",
            Isolation.SUBPROCESS: "subprocess (blast-radius containment, not a security boundary)",
            Isolation.CONTAINER: "container",
            Isolation.VM: "virtual machine",
        }[self]


@dataclass(frozen=True, slots=True)
class Assessment:
    """What is available, what will be used, and what the user should know."""

    effective: Isolation
    best_available: Isolation
    #: True when Bohrin is itself running inside a container or VM — the boundary already
    #: exists around the whole process, so in-process execution inherits it.
    already_contained: bool
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_bounded(self) -> bool:
        return self.effective > Isolation.NONE or self.already_contained

    def to_dict(self) -> dict[str, object]:
        return {
            "effective": self.effective.name.lower(),
            "effective_label": self.effective.label,
            "best_available": self.best_available.name.lower(),
            "already_contained": self.already_contained,
            "notes": list(self.notes),
        }


class UnsafeExecutionError(RuntimeError):
    """Refused to execute a verifier's code with no boundary around it."""


def _in_container() -> bool:
    """Whether this process is already inside a container.

    If it is, the boundary exists around Bohrin as a whole and in-process execution
    inherits it — running an audit inside a container is a legitimate way to be safe.
    """
    if Path("/.dockerenv").exists():
        return True
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8")
    except OSError:
        return False
    return any(marker in cgroup for marker in ("docker", "containerd", "kubepods", "lxc"))


def _docker_usable() -> bool:
    """Docker present *and* responding. Installed-but-not-running is common and is not
    the same as available; treating it as available would fail at the worst moment."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _rlimits_enforced() -> bool:
    """Whether process resource ceilings are actually enforced here.

    macOS does not reliably honour ``RLIMIT_AS`` — there are long-standing CPython issues,
    and on arm64 the call can fail outright for some values. Claiming a ceiling the kernel
    ignores is worse than claiming none, so this is reported rather than assumed.
    """
    return platform.system() == "Linux"


def assess() -> Assessment:
    """Classify the isolation available to this process."""
    notes: list[str] = []
    contained = _in_container()

    if contained:
        notes.append("running inside a container; in-process execution inherits that boundary")
        return Assessment(
            effective=Isolation.NONE,
            best_available=Isolation.CONTAINER,
            already_contained=True,
            notes=tuple(notes),
        )

    if _docker_usable():
        best = Isolation.CONTAINER
        notes.append("docker is available for container-isolated execution")
    elif shutil.which("docker") is not None:
        best = Isolation.SUBPROCESS
        notes.append("docker is installed but not running; container isolation is unavailable")
    else:
        best = Isolation.SUBPROCESS
        notes.append("docker is not installed; container isolation is unavailable")

    if not _rlimits_enforced():
        notes.append(
            f"{platform.system()} does not reliably enforce address-space limits, "
            f"so subprocess ceilings bound wall-clock time but not memory"
        )

    return Assessment(
        effective=Isolation.NONE,
        best_available=best,
        already_contained=False,
        notes=tuple(notes),
    )


def require(assessment: Assessment, *, unsafe_local: bool) -> None:
    """Refuse to proceed when a verifier's code would run with no boundary at all.

    The threat model is stated plainly rather than left implied. Auditing a taskset you
    wrote means executing your own code, where the realistic hazard is an accident — a
    runaway loop, a stray write. Auditing a taskset obtained from a public hub means
    executing a stranger's code, where it is not.

    Bohrin cannot tell those apart, so it refuses by default and makes the caller say which
    situation they are in. ``--unsafe-local`` is the acknowledgement, and it is recorded in
    the report so that a result produced without a boundary is never mistaken for one
    produced with it.
    """
    if assessment.is_bounded or unsafe_local:
        return
    detail = "; ".join(assessment.notes) or "no boundary detected"
    raise UnsafeExecutionError(
        "refusing to execute verifier code with no isolation: scoring runs the taskset's own "
        "reward functions inside this process, which is safe for a taskset you wrote and is "
        "not safe for one you downloaded. "
        f"({detail}). "
        "Start docker and re-run, run bohrin inside a container, or pass --unsafe-local to "
        "accept the risk for a taskset you trust."
    )


__all__ = ["Assessment", "Isolation", "UnsafeExecutionError", "assess", "require"]
