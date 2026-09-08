"""Terminal rendering.

The report leads with the candidate that passed, not with charts. A nine-line submission
scoring full marks on the reader's own task is the argument; everything else is context.
"""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape

from bohrin.ir.evidence import Exploit, Finding, Flake, GroundTruthRejected
from bohrin.probes.base import ProbeResult, ProbeStatus
from bohrin.report.model import Report

_BAR_WIDTH = 15
#: Finding *groups* shown in full. The rest are named in a tail line pointing at --json,
#: because a terminal is a triage surface and the machine-readable output is the full
#: record. Groups rather than findings: 20 tasks failing one operator is one defect, and
#: printing it 20 times is the alert fatigue every vulnerability-management writeup names
#: as the thing that makes a report go unread.
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
    if result.probe_id == "ground_truth_rejected":
        # Must never borrow the acceptance wording. This probe reports the opposite
        # failure, and rendering "N tasks accept known-wrong solutions" over a rejection
        # result states the reverse of what happened -- as an accusation, in the line a
        # reader skims first.
        if not n:
            return "the declared answer was accepted on every task"
        noun = "task" if n == 1 else "tasks"
        return f"the declared answer was refused on {n} {noun} (not scored)"
    if not n:
        return "no accepted wrong solutions"
    if n == 1:
        return "1 task accepts a known-wrong solution"
    return f"{n} tasks accept known-wrong solutions"


def _grouped(report: Report) -> dict[tuple[str, str], list[Finding]]:
    """Collapse findings that share a root cause, preserving report order.

    The key is the operator, because that *is* the mechanism: every task `identity_return`
    lands on fails for one reason, and one fix closes all of them. Grouping by anything
    finer would split a single defect; grouping by anything coarser would merge two.
    """
    groups: dict[tuple[str, str], list[Finding]] = {}
    for result in report.results:
        for finding in result.findings:
            if isinstance(finding, Exploit):
                key = ("exploit", finding.candidate.provenance.operator)
            elif isinstance(finding, GroundTruthRejected):
                key = ("rejected", result.probe_id)
            else:
                key = ("flake", result.probe_id)
            groups.setdefault(key, []).append(finding)
    return groups


def _zero_score_caveat(report: Report) -> str | None:
    """What a clean score does and does not mean.

    A gap of 0 is an *under-approximation*: Bohrin reports only defects its operators can
    construct a payload for, so absence of findings is absence of evidence, not evidence
    of absence. Two of the environments in this project's own sweep score 0 and are
    nonetheless exploitable — `glossary` grades by substring containment, `proposer_solver`
    by the last integer in the reply — and no model-free operator here builds those
    payloads.

    `docs/05_ROBUSTNESS.md` has always said so. The report did not, and the report is what
    people read; a reader who concludes "my verifier is fine" from a clean run has been
    misled by omission. That is the same failure as a false accusation, pointed the other
    way, and it is the one a certification product can least afford.
    """
    if report.gap.score is None or report.gap.score > 0:
        return None
    operators = sorted({op for result in report.results for op in (result.detail.get("operators") or ())})
    count = len(operators) if operators else None
    which = f"the {count} model-free operators" if count else "the model-free operators"
    return (
        f"a clean result bounds what {which} could construct — it is not a proof that the "
        f"verifier is sound. Graders that accept by substring or by the last number in a "
        f"reply score 0 here and are still exploitable."
    )


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
        # A probe kept out of the Verification Gap must not draw a full bar: the bar reads
        # as severity, and severity is exactly the claim this probe declines to make.
        if result.detail.get("scored_out_of_gap"):
            fraction = 0.0
        colour = "yellow" if result.status is ProbeStatus.OK else "dim"
        console.print(
            f"  [{colour}]{result.probe_id:<14}[/{colour}] {_bar(fraction)}  {escape(_headline(result))}",
            highlight=False,
        )

    console.print()
    # The gap and its coverage are rendered by GapScore.__str__ so the two cannot drift
    # apart, and so no caller can accidentally print a bare number.
    console.print(f"  [bold]{escape(str(report.gap))}[/bold]")
    caveat = _zero_score_caveat(report)
    if caveat is not None:
        console.print(f"  [dim]note {escape(caveat)}[/dim]", highlight=False)
    console.print()

    groups = _grouped(report)
    shown = 0
    for (_kind, label), findings in list(groups.items())[:_DETAIL_LIMIT]:
        first_finding = findings[0]
        shown += len(findings)
        tasks = len({f.task_id for f in findings})
        if isinstance(first_finding, Exploit):
            if tasks == 1:
                console.print(f"  [red]EXPLOIT[/red] ▸ {escape(first_finding.summary)}", highlight=False)
            else:
                # One defect, stated once. The count is the severity signal; the worked
                # example below is the evidence. Printing the same operator N times buries
                # a second, different defect under the first one's repetitions.
                console.print(
                    f"  [red]EXPLOIT[/red] ▸ {escape(label)} accepted on "
                    f"{_plural(tasks, 'task')} [dim](reward {first_finding.verdict.reward:g})[/dim]",
                    highlight=False,
                )
            console.print(f"           [dim]{escape(first_finding.candidate.provenance.detail)}[/dim]", highlight=False)
            payload = first_finding.candidate.payload.strip() or "(empty)"
            line = payload.splitlines()[0] if payload.splitlines() else payload
            # Mark the cut. Truncating mid-word with no ellipsis reads as a rendering
            # bug rather than an abbreviation, and the payload is the evidence.
            first = line if len(line) <= _PAYLOAD_CHARS else line[: _PAYLOAD_CHARS - 1].rstrip() + "…"
            prefix = "submitted" if tasks == 1 else f"example (task {escape(first_finding.task_id)})"
            console.print(f"           {prefix}: [cyan]{escape(first)}[/cyan]", highlight=False)
        elif isinstance(first_finding, GroundTruthRejected):
            # Worded as a search budget, never as a verdict. This finding is reported
            # outside the Verification Gap because a rejection can also be a documented
            # output contract being enforced correctly, and the line has to say so or a
            # reader will take it as an accusation.
            tried = len(first_finding.relations_tried)
            noun = "task" if tasks == 1 else "tasks"
            console.print(
                f"  [yellow]REJECTED[/yellow] ▸ the declared answer was refused on "
                f"{tasks} {noun} [dim](not scored)[/dim]",
                highlight=False,
            )
            console.print(
                f"           [dim]{tried} certified meaning-preserving renderings tried; none "
                f"accepted. This is a lead, not a verdict: a verifier enforcing an output "
                f"format the prompt documents, and one whose reward never reads the reply at "
                f"all, both look exactly like this.[/dim]",
                highlight=False,
            )
            console.print(
                f"           example (task {escape(first_finding.task_id)}): "
                f"[cyan]{escape(first_finding.reference[:_PAYLOAD_CHARS])}[/cyan]",
                highlight=False,
            )
        elif isinstance(first_finding, Flake):
            if tasks == 1:
                console.print(f"  [yellow]FLAKE[/yellow]   ▸ {escape(first_finding.summary)}", highlight=False)
            else:
                console.print(
                    f"  [yellow]FLAKE[/yellow]   ▸ identical submissions scored inconsistently on "
                    f"{_plural(tasks, 'task')}",
                    highlight=False,
                )
        console.print(f"           [dim]{escape(report.command_for(first_finding))}[/dim]", highlight=False)
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
