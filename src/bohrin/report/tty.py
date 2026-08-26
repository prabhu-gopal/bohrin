"""The terminal renderer — Stage ⑥ default output (docs/02 §6, docs/05 §2).

Turns a finished :class:`Report` into a ranked, skimmable summary: the Quality Score, the
severity tally, the ranked clusters, and the mechanism+fix for the top finding. Pure sink —
it never mutates the report. Localizes its chrome via a :class:`Catalog` (docs/05 §7).
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from bohrin.ir.schema import Severity
from bohrin.report.messages import catalog
from bohrin.report.model import Report

#: Clusters shown with their full why/fix in the terminal. Beyond this the TTY summarizes
#: and points at the fuller reports — a first run must stay skimmable (docs/05 §2).
#:
#: Five, not six, because the 20-dataset benchmark measured a median of 9.5 findings per
#: dataset with every dataset producing at least one. At that density the terminal is the
#: triage surface, not the full record: a reader who has to scroll has already stopped
#: reading. Nothing is dropped — `--json`, `--sarif` and `--html` all carry every finding.
_DETAIL_LIMIT = 5

_SEV_STYLE: dict[Severity, str] = {
    Severity.HIGH: "bold red",
    Severity.MEDIUM: "yellow",
    Severity.LOW: "cyan",
    Severity.INFO: "dim",
}


class TtyRenderer:
    """Renders a report to the terminal (and to a string for tests). A :class:`Renderer`."""

    def render(self, report: Report, *, lang: str | None = None) -> str:
        """Render to a plain string (used by tests and non-TTY sinks)."""
        console = Console(record=True, width=100, force_terminal=False)
        self.emit(report, console, lang=lang)
        return console.export_text()

    def print(self, report: Report, console: Console | None = None, *, lang: str | None = None) -> None:
        """Render to a live terminal."""
        self.emit(report, console or Console(), lang=lang)

    def emit(self, report: Report, console: Console, *, lang: str | None = None) -> None:
        cat = catalog(lang)
        d = report.dataset
        console.print(Text.assemble(("bohrin", "bold green"), ("  ·  ", "dim"), (d.uri, "bold")))
        episodes_bit = (
            f"{d.n_episodes} of {d.total_episodes} episodes (triage)" if d.sampled else f"{d.n_episodes} episodes"
        )
        meta = f"{d.format} · {episodes_bit}"
        if d.embodiment:
            meta += f" · {d.embodiment}"
        if d.control_hz:
            meta += f" · {d.control_hz:.0f} Hz"
        if d.action_dim is not None:
            meta += f" · action_dim {d.action_dim}"
        console.print(Text(meta, style="dim"))

        counts = report.counts
        tally = "   ".join(
            Text.assemble((f"{counts[s]} {cat.severity[s]}", _SEV_STYLE[s])).plain
            for s in (Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO)
            if counts[s]
        )
        # The headline is the severity tally, not an aggregate score. Counts are a fact
        # about what we found; a score would be a claim about what it costs you.
        if not report.clusters:
            console.print(Text(cat.no_findings, style="green"))
            return
        console.print(Panel.fit(Text(tally, style="bold")))

        families = report.family_counts()
        if families:
            console.print(
                Text(f"{cat.by_family}: " + "  ".join(f"{cat.family[f]} {n}" for f, n in families.items()), style="dim")
            )
        console.print()

        # docs/05 §2: every cluster carries its own "why + fix", not just the top one —
        # a user must not have to open the HTML report to learn what to do about #3.
        for c in report.clusters[:_DETAIL_LIMIT]:
            console.print(
                Text.assemble(
                    (f"{cat.severity[c.severity]:<7}", _SEV_STYLE[c.severity]),
                    ("▸ ", "dim"),
                    (c.title, "bold"),
                )
            )
            console.print(Text(f"         → {c.fix.text}", style="none"))
            console.print(Text(f"           {c.blast_radius.n_episodes} eps  [{c.id}]", style="dim"))
            console.print()

        remaining = len(report.clusters) - _DETAIL_LIMIT
        if remaining > 0:
            # Name the flag that actually shows the rest. Deliberately *not* `--all`: that
            # flag adds the DEFAULT_EXCLUDED detectors, which are held back precisely
            # because they over-report, so pointing a user there to see more findings would
            # hand them the least trustworthy ones first.
            console.print(Text(f"… {remaining} {cat.more_findings} — --html or --json for all.", style="dim"))
        if report.dataset.sampled:
            triage = (
                f"Triage scan of {report.dataset.n_episodes}/{report.dataset.total_episodes} episodes — --full for all."
            )
            console.print(Text(triage, style="dim"))
        console.print(Text(f"{cat.next_hint}: bohrin scan {report.dataset.uri} --html report.html --open", style="dim"))
