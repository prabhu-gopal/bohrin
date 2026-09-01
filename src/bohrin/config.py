"""Audit configuration."""

from __future__ import annotations

import os
import platform
import re
import subprocess
from dataclasses import dataclass, field

#: Repeats used by the determinism probe. Five is enough to catch a coin-flip verifier
#: with high probability while keeping a 40-task audit to a few hundred calls.
DEFAULT_REPEATS = 5


def default_concurrency() -> int:
    """A concurrency that is useful without crowding a laptop.

    Scoring is I/O-bound in principle, but a reward function can do arbitrary work, so the
    ceiling is derived from the machine rather than fixed. Free memory is the binding
    constraint on a small machine, not core count: eight reward functions that each build a
    large structure will exhaust RAM long before they exhaust the CPU.
    """
    cores = os.cpu_count() or 2
    ceiling = max(2, min(8, cores - 1))

    free_gb = _free_memory_gb()
    if free_gb is not None and free_gb < 4.0:
        # Leave headroom rather than competing with the rest of the machine.
        return max(2, min(ceiling, 3))
    return ceiling


def _free_memory_gb() -> float | None:
    """Best-effort free memory, or None where it cannot be determined cheaply.

    macOS exposes no ``SC_AVPHYS_PAGES``, so the POSIX route silently returns nothing
    there — which would leave the memory guard permanently disabled on exactly the kind of
    laptop it exists to protect. ``vm_stat`` is parsed as a fallback.
    """
    try:
        if hasattr(os, "sysconf") and "SC_AVPHYS_PAGES" in os.sysconf_names:
            pages = os.sysconf("SC_AVPHYS_PAGES")
            size = os.sysconf("SC_PAGE_SIZE")
            return float(pages) * float(size) / 1024**3
    except (OSError, ValueError):
        pass

    if platform.system() == "Darwin":
        return _darwin_free_memory_gb()
    return None


def _darwin_free_memory_gb() -> float | None:
    """Reclaimable memory on macOS, from ``vm_stat``.

    Counts free, inactive and speculative pages: inactive pages are reclaimable under
    pressure, so counting only "free" would understate availability badly and throttle the
    audit for no reason.
    """
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None

    match = re.search(r"page size of (\d+) bytes", out)
    page_size = int(match.group(1)) if match else 4096
    pages = 0
    for label in ("Pages free", "Pages inactive", "Pages speculative"):
        found = re.search(rf"{label}:\s+(\d+)", out)
        if found:
            pages += int(found.group(1))
    return (pages * page_size) / 1024**3 if pages else None


@dataclass(frozen=True, slots=True)
class ScanConfig:
    """Everything an audit needs that is not the environment itself."""

    #: Maximum reward invocations in flight. Bounded because unbounded parallelism against
    #: a customer's environment is a denial-of-service on the thing we were asked to audit.
    #: See :func:`default_concurrency` for how the CLI picks this.
    concurrency: int = 8

    #: Seconds allowed for a single reward invocation before it is recorded as an error.
    per_task_timeout: float = 30.0

    #: Cap on tasks probed; None means every task.
    max_tasks: int | None = None

    #: Repeats for the determinism probe.
    repeats: int = DEFAULT_REPEATS

    #: Probe ids to run. Empty means "every discovered probe not in DEFAULT_EXCLUDED".
    only: frozenset[str] = field(default_factory=frozenset)

    #: Run every probe including those held back from a default audit.
    all_probes: bool = False

    #: Permit execution without a verified isolation boundary. Off by default.
    unsafe_local: bool = False
