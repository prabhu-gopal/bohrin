"""Command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from bohrin.adapters.base import MissingExtraError, TasksetLoadError, TaskSource, UnknownFormatError
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
_USER_ERRORS = (UnknownFormatError, MissingExtraError, TasksetLoadError, FileNotFoundError, UnsafeExecutionError)

#: Exit codes. Chosen to match the convention `semgrep` established and `trivy` follows,
#: because a CI author should not have to learn a per-tool dialect: 0 clean, 1 findings,
#: 2 fatal/input error. Code 3 is ours and is the point of the design — see `_gate`.
EXIT_CLEAN, EXIT_FINDINGS, EXIT_USER_ERROR, EXIT_UNDECIDED = 0, 1, 2, 3


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
            "  bohrin audit ./envs --fail-on-gap 20       fail a CI job above a gap of 20\n"
            "\n"
            "exit codes:\n"
            "  0  audit ran; no gate, or the gate passed\n"
            "  1  a gate was set and the audit is over it\n"
            "  2  bad input, or the taskset could not be loaded\n"
            "  3  a gate was set but coverage was incomplete — no verdict, not a pass\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"bohrin {__version__}")
    parser.add_argument("--no-color", action="store_true", help="disable colored output")

    # Also accepted *after* the subcommand. `bohrin audit ./env --no-color` is what a user
    # types, and argparse would otherwise reject it as an unrecognised argument. SUPPRESS
    # is load-bearing: without it the subparser's own False default overwrites a --no-color
    # given before the subcommand, and the global form silently stops working.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", parents=[shared], help="probe a taskset's verifier")
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
    audit.add_argument(
        "--fail-on-finding",
        action="store_true",
        help="exit 1 if the audit reports any finding (for CI)",
    )
    audit.add_argument(
        "--fail-on-gap",
        type=float,
        default=None,
        metavar="SCORE",
        help="exit 1 if the Verification Gap is at or above SCORE (0-100)",
    )

    sub.add_parser("list-probes", parents=[shared], help="list registered probes")

    explain = sub.add_parser("explain", parents=[shared], help="explain one probe")
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
        # Before the isolation gate: a missing extra blocks the audit at every isolation
        # level, so leading with "start docker" sends the user to fix the wrong thing and
        # they meet the real problem only on the second run. This imports nothing from the
        # taskset — see Adapter.check_requirements.
        adapter.check_requirements()
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
        return EXIT_USER_ERROR

    probes = probe_registry.discover(include_excluded=args.all_probes)
    if config.only:
        probes = [p for p in probes if p.id in config.only]
    if not probes:
        err.print("[red]error[/red] no probes selected", highlight=False)
        return EXIT_USER_ERROR

    results = asyncio.run(_run_probes(source, probes, config))
    report = Report(
        target=str(path),
        adapter=adapter.name,
        gap=verification_gap(results, probes),
        results=tuple(results),
        tasks_total=max((r.tasks_probed for r in results), default=0),
        # getattr, not an attribute access: `corpus_total` is an optional part of the
        # adapter contract, and an adapter written against the previous one must keep working.
        corpus_total=getattr(source, "corpus_total", None),
        isolation=isolation,
    )

    render(report, console)

    if args.json_path:
        Path(args.json_path).write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
        console.print(f"[dim]report written to {escape(args.json_path)}[/dim]")

    return _gate(args, report, err)


def _gate(args: argparse.Namespace, report: Report, err: Console) -> int:
    """Turn the report into an exit code, but only when the user asked for a gate.

    Gating is opt-in, as it is in ``semgrep scan`` and ``trivy``: a bare ``bohrin audit``
    stays exit 0 so that adding a gate is never a silent breaking change for anyone
    already scripting against it.

    **The part that is not copied from anywhere.** Trivy's documented trap is that its
    default exit code is 0 even on critical findings, so a pipeline missing the flag
    merges happily. Bohrin has a worse version of that failure available to it: a gate can
    pass because nothing was *found*, or because nothing was *measured*, and those are not
    the same claim. A verifier whose probes all errored has a gap of ``None``, and any
    numeric comparison against it would quietly read as clean.

    So an unevaluable gate gets its own code rather than being folded into pass or fail.
    This is the same distinction SARIF draws with ``invocation.executionSuccessful`` and
    error-level ``toolExecutionNotifications``: a result set that is incomplete has to say
    so, because a reader cannot tell from the results alone. Exit 3 lets a pipeline treat
    "we could not tell" differently from "it is clean", which is the entire point.
    """
    if not args.fail_on_finding and args.fail_on_gap is None:
        return EXIT_CLEAN

    gap = report.gap
    if gap.score is None:
        err.print(
            "[red]gate not evaluated[/red] no probe produced a measurement, so the audit "
            "has no verdict to gate on — this is not a clean result.",
            highlight=False,
        )
        return EXIT_UNDECIDED
    # Only a probe that *failed* leaves the verdict undecided. A probe that does not
    # **apply** -- `ground_truth_rejected` on a taskset with no declared answer, or
    # `weak_oracle` when --operator selected none -- has nothing to measure rather than an
    # unmeasured gap, and blocking on it would fail a CI job for a clean environment. That
    # regression was real: adding a third probe made four clean public environments exit 3.
    failed = [r.probe_id for r in report.results if r.status is ProbeStatus.ERROR]
    if failed:
        err.print(
            f"[red]gate not evaluated[/red] {', '.join(sorted(failed))} could not measure "
            f"this taskset ({gap.coverage} completed), so a passing score would understate "
            f"the gap — fix the cause, or drop the gate.",
            highlight=False,
        )
        return EXIT_UNDECIDED

    findings = sum(len(r.findings) for r in report.results)
    if args.fail_on_finding and findings:
        err.print(
            f"[red]gate failed[/red] {findings} finding{'' if findings == 1 else 's'} reported.",
            highlight=False,
        )
        return EXIT_FINDINGS
    if args.fail_on_gap is not None and gap.score >= args.fail_on_gap:
        err.print(
            f"[red]gate failed[/red] Verification Gap {gap.score:.0f} is at or above the "
            f"{args.fail_on_gap:.0f} threshold.",
            highlight=False,
        )
        return EXIT_FINDINGS
    return EXIT_CLEAN


def _cmd_list_probes(console: Console) -> int:
    probes = probe_registry.discover(include_excluded=True)
    if not probes:
        console.print("[dim]no probes registered[/dim]")
        return EXIT_CLEAN
    for probe in probes:
        held = " [dim](held back; use --all)[/dim]" if probe.id in probe_registry.DEFAULT_EXCLUDED else ""
        console.print(f"[bold]{probe.id}[/bold]  [dim]({probe.family})[/dim]{held}")
    return EXIT_CLEAN


def _cmd_explain(probe_id: str, console: Console, err: Console) -> int:
    probe = probe_registry.get(probe_id)
    if probe is None:
        known = ", ".join(p.id for p in probe_registry.discover(include_excluded=True)) or "none"
        err.print(f"[red]unknown probe:[/red] {escape(probe_id)}. Registered: {known}", highlight=False)
        return EXIT_USER_ERROR
    console.print(f"[bold]{probe.id}[/bold]  [dim]({probe.family})[/dim]\n")
    console.print(probe.explain())
    return EXIT_CLEAN


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    no_color = getattr(args, "no_color", False)
    console = Console(no_color=no_color or None)
    err = Console(stderr=True, no_color=no_color or None)

    if args.command == "audit":
        return _cmd_audit(args, console, err)
    if args.command == "list-probes":
        return _cmd_list_probes(console)
    if args.command == "explain":
        return _cmd_explain(args.probe_id, console, err)
    return EXIT_USER_ERROR


def _run() -> None:
    """Console-script wrapper: turn Ctrl-C into a clean exit rather than a traceback."""
    try:
        sys.exit(main())
    except KeyboardInterrupt:  # pragma: no cover - requires a real SIGINT
        sys.exit(130)


__all__ = ["main"]
