"""Terminal rendering.

The report leads with the candidate that passed, not with charts. A nine-line submission
scoring full marks on the reader's own task is the argument; everything else is context.
"""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape

from bohrin.ir.evidence import Exploit, Flake
from bohrin.probes.base import ProbeResult, ProbeStatus
from bohrin.report.model import Report

_BAR_WIDTH = 15
#: Findings shown in full. The rest are named in a tail line pointing at --json, because a
#: terminal is a triage surface and the machine-readable output is the full record.
_DETAIL_LIMIT = 6

#: Characters of a payload's first line shown before it is elided. The full payload is in
#: the JSON; this is the identifying glimpse.
_PAYLOAD_CHARS = 96


def _plural(count: int, noun: str) -> str:
    """`1 task`, `2 tasks`. "1 tasks" in a report that sells rigour is a bad first look."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _bar(fraction: float) -> str:
    filled = max(0, min(_BAR_WIDTH, round(fraction * _BAR_WIDTH)))
    return "█" * filled + "░" * (_BAR_WIDTH - filled)


def _headline(result: ProbeResult) -> str:
    if result.status is ProbeStatus.NOT_APPLICABLE:
        return f"not applicable — {result.reason}"
    if result.status is ProbeStatus.ERROR:
        return f"error — {result.reason}"
    # Count distinct tasks, not findings: several findings can share a task, and reporting
    # "40 tasks" for a 4-task environment is worse than reporting nothing.
    n = len({f.task_id for f in result.findings})
    if result.probe_id == "determinism":
        if n:
            return f"{_plural(n, 'task')} score{'s' if n == 1 else ''} inconsistently"
        repeats = result.detail.get("repeats")
        # "no variance observed in N runs" is what was measured. "deterministic" is not.
        return f"no variance observed in {repeats} runs" if repeats else "no variance observed"
    if not n:
        return "no accepted wrong solutions"
    if n == 1:
        return "1 task accepts a known-wrong solution"
    return f"{n} tasks accept known-wrong solutions"


def render(report: Report, console: Console) -> None:
    """Print the audit."""
    console.print()
    console.print(f"[bold]Bohrin[/bold]  ·  {escape(report.target)}")
    line = f"{report.adapter} · {_plural(report.tasks_total, 'task')} · {_plural(len(report.results), 'probe')}"
    if report.isolation is not None:
        line += f" · isolation: {report.isolation.effective.name.lower()}"
    console.print(f"[dim]{escape(line)}[/dim]")
    if report.isolation is not None and not report.isolation.is_bounded:
        console.print(
            "  [yellow]note[/yellow] verifier code ran in-process with no isolation boundary",
            highlight=False,
        )
    console.print()

    for result in report.results:
        fraction = result.sub_score if result.sub_score is not None else 0.0
        colour = "yellow" if result.status is ProbeStatus.OK else "dim"
        console.print(
            f"  [{colour}]{result.probe_id:<14}[/{colour}] {_bar(fraction)}  {escape(_headline(result))}",
            highlight=False,
        )

    console.print()
    # The gap and its coverage are rendered by GapScore.__str__ so the two cannot drift
    # apart, and so no caller can accidentally print a bare number.
    console.print(f"  [bold]{escape(str(report.gap))}[/bold]")
    console.print()

    shown = 0
    for result in report.results:
        for finding in result.findings:
            if shown >= _DETAIL_LIMIT:
                break
            shown += 1
            if isinstance(finding, Exploit):
                console.print(f"  [red]EXPLOIT[/red] ▸ {escape(finding.summary)}", highlight=False)
                console.print(f"           [dim]{escape(finding.candidate.provenance.detail)}[/dim]", highlight=False)
                payload = finding.candidate.payload.strip() or "(empty)"
                line = payload.splitlines()[0] if payload.splitlines() else payload
                # Mark the cut. Truncating mid-word with no ellipsis reads as a rendering
                # bug rather than an abbreviation, and the payload is the evidence.
                first = line if len(line) <= _PAYLOAD_CHARS else line[: _PAYLOAD_CHARS - 1].rstrip() + "…"
                console.print(f"           submitted: [cyan]{escape(first)}[/cyan]", highlight=False)
            elif isinstance(finding, Flake):
                console.print(f"  [yellow]FLAKE[/yellow]   ▸ {escape(finding.summary)}", highlight=False)
            console.print(f"           [dim]{escape(report.command_for(finding))}[/dim]", highlight=False)
            console.print()

    remaining = report.findings - shown
    if remaining > 0:
        console.print(f"  [dim]{_plural(remaining, 'more finding')} — see --json for the full record[/dim]")
        console.print()

    # A task that could not be measured must be visible. Reporting "no findings" over a
    # taskset that was silently reduced would let a user believe their whole environment
    # was audited when part of it never ran.
    for result in report.results:
        skipped = result.detail.get("baseline_failures") or []
        if not skipped:
            continue
        console.print(
            f"  [yellow]note[/yellow] {_plural(len(skipped), 'task')} could not be measured by "
            f"{escape(result.probe_id)} and are excluded from its score",
            highlight=False,
        )
        for entry in list(skipped)[:3]:
            console.print(
                f"           [dim]{escape(str(entry.get('task_id')))}: "
                f"{escape(str(entry.get('reason', ''))[:120])}[/dim]",
                highlight=False,
            )
        if len(skipped) > 3:
            console.print(f"           [dim]... and {len(skipped) - 3} more; see --json[/dim]")
        console.print()

    if report.unverified:
        console.print(
            f"  [dim]note {_plural(report.unverified, 'accepted candidate')} could not be shown to be wrong; "
            f"reported as leads, excluded from the gap[/dim]",
            highlight=False,
        )
        console.print()


__all__ = ["render"]
