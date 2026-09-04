"""Command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from bohrin.adapters.base import MissingExtraError, TaskSource, UnknownFormatError
from bohrin.adapters.registry import detect
from bohrin.config import DEFAULT_REPEATS, ScanConfig, default_concurrency
from bohrin.execute.isolation import UnsafeExecutionError, assess, require
from bohrin.probes import registry as probe_registry
from bohrin.probes.base import Probe, ProbeResult, ProbeStatus
from bohrin.report.model import Report
from bohrin.report.tty import render
from bohrin.scoring.gap import verification_gap
from bohrin.version import __version__

#: Errors that mean "fix your input", printed as a message rather than a traceback.
_USER_ERRORS = (UnknownFormatError, MissingExtraError, FileNotFoundError, UnsafeExecutionError)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bohrin",
        description="Audits the verifier, not the model.",
        epilog=(
            "examples:\n"
            "  bohrin audit ./environments/my-taskset     audit a local taskset\n"
            "  bohrin audit ./envs --json report.json     write the machine-readable report\n"
            "  bohrin list-probes                         show what will run\n"
            "  bohrin explain weak_oracle                 what a probe asks, and why\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"bohrin {__version__}")
    parser.add_argument("--no-color", action="store_true", help="disable colored output")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="probe a taskset's verifier")
    audit.add_argument("path", help="path to the taskset")
    audit.add_argument("--json", dest="json_path", metavar="FILE", help="write the full report as JSON")
    audit.add_argument("--probe", action="append", default=[], metavar="ID", help="run only this probe (repeatable)")
    audit.add_argument("--all", dest="all_probes", action="store_true", help="include probes held back by default")
    audit.add_argument("--max-tasks", type=int, default=None, metavar="N", help="probe at most N tasks")
    audit.add_argument("--task", action="append", default=[], metavar="ID", help="probe only this task id (repeatable)")
    audit.add_argument(
        "--operator", action="append", default=[], metavar="ID", help="apply only this operator (repeatable)"
    )
    audit.add_argument("--repeats", type=int, default=DEFAULT_REPEATS, metavar="N", help="determinism repeats")
    audit.add_argument(
        "--concurrency",
        type=int,
        default=0,
        metavar="N",
        help="max scoring calls in flight (0 = choose from CPU count and free memory)",
    )
    audit.add_argument(
        "--unsafe-local",
        action="store_true",
        help="run verifier code in-process with no isolation; only for a taskset you trust",
    )
    audit.add_argument("--timeout", type=float, default=30.0, metavar="SEC", help="per-call timeout")

    sub.add_parser("list-probes", help="list registered probes")

    explain = sub.add_parser("explain", help="explain one probe")
    explain.add_argument("probe_id", help="probe id, e.g. weak_oracle")

    return parser


async def _run_probes(source: TaskSource, probes: list[Probe], config: ScanConfig) -> list[ProbeResult]:
    """Run each probe, capturing failures so one cannot abandon the audit."""
    results: list[ProbeResult] = []
    for probe in probes:
        try:
            results.append(await probe.run(source, config))
        except Exception as exc:  # a probe must never take down the audit
            results.append(
                ProbeResult(
                    probe_id=probe.id,
                    status=ProbeStatus.ERROR,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
    return results


def _cmd_audit(args: argparse.Namespace, console: Console, err: Console) -> int:
    path = Path(args.path)
    isolation = assess()
    try:
        # Detection reads files only and executes nothing, so it runs first: telling a user
        # about isolation when their path is simply wrong is unhelpful. The boundary check
        # comes immediately before load(), which imports the taskset package and therefore
        # runs its module-level code — that is the first moment foreign code executes.
        adapter = detect(path)
        require(isolation, unsafe_local=args.unsafe_local)
        config = ScanConfig(
            concurrency=args.concurrency or default_concurrency(),
            per_task_timeout=args.timeout,
            max_tasks=args.max_tasks,
            repeats=args.repeats,
            only=frozenset(args.probe),
            only_tasks=frozenset(args.task),
            only_operators=frozenset(args.operator),
            all_probes=args.all_probes,
            unsafe_local=args.unsafe_local,
        )
        source = adapter.load(path, config)
    except _USER_ERRORS as exc:
        err.print(f"[red]error[/red] {escape(str(exc))}", highlight=False)
        return 2

    probes = probe_registry.discover(include_excluded=args.all_probes)
    if config.only:
        probes = [p for p in probes if p.id in config.only]
    if not probes:
        err.print("[red]error[/red] no probes selected", highlight=False)
        return 2

    results = asyncio.run(_run_probes(source, probes, config))
    report = Report(
        target=str(path),
        adapter=adapter.name,
        gap=verification_gap(results, probes),
        results=tuple(results),
        tasks_total=max((r.tasks_probed for r in results), default=0),
        isolation=isolation,
    )

    render(report, console)

    if args.json_path:
        Path(args.json_path).write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
        console.print(f"[dim]report written to {escape(args.json_path)}[/dim]")

    return 0


def _cmd_list_probes(console: Console) -> int:
    probes = probe_registry.discover(include_excluded=True)
    if not probes:
        console.print("[dim]no probes registered[/dim]")
        return 0
    for probe in probes:
        held = " [dim](held back; use --all)[/dim]" if probe.id in probe_registry.DEFAULT_EXCLUDED else ""
        console.print(f"[bold]{probe.id}[/bold]  [dim]({probe.family})[/dim]{held}")
    return 0


def _cmd_explain(probe_id: str, console: Console, err: Console) -> int:
    probe = probe_registry.get(probe_id)
    if probe is None:
        known = ", ".join(p.id for p in probe_registry.discover(include_excluded=True)) or "none"
        err.print(f"[red]unknown probe:[/red] {escape(probe_id)}. Registered: {known}", highlight=False)
        return 1
    console.print(f"[bold]{probe.id}[/bold]  [dim]({probe.family})[/dim]\n")
    console.print(probe.explain())
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    console = Console(no_color=args.no_color or None)
    err = Console(stderr=True, no_color=args.no_color or None)

    if args.command == "audit":
        return _cmd_audit(args, console, err)
    if args.command == "list-probes":
        return _cmd_list_probes(console)
    if args.command == "explain":
        return _cmd_explain(args.probe_id, console, err)
    return 2


def _run() -> None:
    """Console-script wrapper: turn Ctrl-C into a clean exit rather than a traceback."""
    try:
        sys.exit(main())
    except KeyboardInterrupt:  # pragma: no cover - requires a real SIGINT
        sys.exit(130)


__all__ = ["main"]
