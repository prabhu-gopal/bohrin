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
            return f"{n} task(s) score inconsistently"
        repeats = result.detail.get("repeats")
        # "no variance observed in N runs" is what was measured. "deterministic" is not.
        return f"no variance observed in {repeats} runs" if repeats else "no variance observed"
    return f"{n} task(s) accept known-wrong solutions" if n else "no accepted wrong solutions"


def render(report: Report, console: Console) -> None:
    """Print the audit."""
    console.print()
    console.print(f"[bold]Bohrin[/bold]  ·  {escape(report.target)}")
    console.print(f"[dim]{report.adapter} · {report.tasks_total} tasks · {len(report.results)} probes[/dim]")
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
                first = payload.splitlines()[0][:96] if payload.splitlines() else payload
                console.print(f"           submitted: [cyan]{escape(first)}[/cyan]", highlight=False)
            elif isinstance(finding, Flake):
                console.print(f"  [yellow]FLAKE[/yellow]   ▸ {escape(finding.summary)}", highlight=False)
            console.print(f"           [dim]{escape(finding.repro)}[/dim]", highlight=False)
            console.print()

    remaining = report.findings - shown
    if remaining > 0:
        console.print(f"  [dim]{remaining} more finding(s) — see --json for the full record[/dim]")
        console.print()

    # A task that could not be measured must be visible. Reporting "no findings" over a
    # taskset that was silently reduced would let a user believe their whole environment
    # was audited when part of it never ran.
    for result in report.results:
        skipped = result.detail.get("baseline_failures") or []
        if not skipped:
            continue
        console.print(
            f"  [yellow]note[/yellow] {len(skipped)} task(s) could not be measured by "
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
            f"  [dim]note {report.unverified} accepted candidate(s) could not be shown to be wrong; "
            f"reported as leads, excluded from the gap[/dim]",
            highlight=False,
        )
        console.print()


__all__ = ["render"]
