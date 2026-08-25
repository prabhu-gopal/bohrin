"""The ``bohrin`` command-line interface (docs/05 §3).

Thin argument parsing over :func:`bohrin.api.scan` and the registries. The core command is
``scan``; ``list-detectors`` and ``explain`` support discovery and learning. Kept on the
stdlib ``argparse`` so the core install pulls no CLI framework.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import yaml
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn, TimeElapsedColumn

from bohrin.adapters._mapping import UnmappableDatasetError
from bohrin.adapters.registry import UnknownFormatError
from bohrin.api import scan
from bohrin.config import DEFAULT_FPR, ScanConfig
from bohrin.detectors.registry import discover as discover_detectors
from bohrin.engine import ProgressFn
from bohrin.hub import HubUnavailableError
from bohrin.ir.schema import Severity
from bohrin.policy.loader import UnreadablePolicyError
from bohrin.policy.target import UnknownTargetError
from bohrin.profile.episode_reservoir import DEFAULT_MEMORY_BUDGET_MB
from bohrin.report.messages import is_supported, supported_languages
from bohrin.report.model import Report
from bohrin.report.tty import TtyRenderer
from bohrin.version import __version__


def _split_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


#: Exceptions that mean "the user gave us something we can't use", as opposed to a bug.
#: Reported as a one-line message with exit code 2, never as a traceback.
_USER_ERRORS = (
    UnknownFormatError,
    UnmappableDatasetError,
    UnreadablePolicyError,
    UnknownTargetError,
    HubUnavailableError,
    FileNotFoundError,
)

_STAGE_LABEL = {"fetch": "fetching from the Hub", "profile": "building profile", "detect": "running detectors"}


@contextmanager
def _progress(console: Console, *, quiet: bool) -> Iterator[ProgressFn | None]:
    """Yield a progress sink that drives a live Rich bar, or ``None`` under ``--ci``.

    Progress is presentation only — it never reaches the report, so a scan is identical
    with or without a terminal attached.
    """
    if quiet or not console.is_terminal:
        yield None
        return

    bar = Progress(
        SpinnerColumn(style="green"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=28, complete_style="green"),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )
    tasks: dict[str, TaskID] = {}

    def sink(stage: str, done: int, total: int | None) -> None:
        label = _STAGE_LABEL.get(stage, stage)
        if stage not in tasks:
            tasks[stage] = bar.add_task(label, total=total)
        bar.update(tasks[stage], completed=done, total=total)

    with bar:
        yield sink


_ROOT_HELP = """The health check-up for robot-learning datasets.

examples:
  bohrin scan ./my_lerobot_dataset          scan a local dataset
  bohrin scan lerobot/pusht                 scan a dataset on the Hugging Face Hub
  bohrin scan ./data --json report.json     write the machine-readable report

Run `bohrin scan --help` for the full scan options."""

_ROOT_EPILOG = "Docs and issues: https://github.com/bohrin/bohrin"

_SCAN_HELP = """Analyze a dataset and report the defects that will hurt training.

examples:
  bohrin scan ./my_lerobot_dataset
  bohrin scan lerobot/pusht
  bohrin scan ./data --json report.json
  bohrin scan ./data --ci --fail-on HIGH    exit 1 when a HIGH finding is present"""

_SCAN_EPILOG = """exit codes:
  0  the scan completed (findings alone never change this)
  1  an internal error, or the --ci --fail-on gate tripped
  2  a usage error: bad path, unknown format, unreadable checkpoint

Findings go to stdout; errors, notices and progress go to stderr."""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bohrin",
        description=_ROOT_HELP,
        epilog=_ROOT_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"bohrin {__version__}")
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colour and styling. Also honoured via the NO_COLOR environment variable, "
        "and applied automatically when output is not a terminal.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser(
        "scan",
        help="Analyze a dataset (the core command).",
        description=_SCAN_HELP,
        epilog=_SCAN_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    scan_p.add_argument("path", help="Local dataset path, or a Hugging Face Hub repo id (owner/name).")
    scan_p.add_argument("--format", help="Override format autodetection.")
    scan_p.add_argument("--policy", help="Checkpoint enabling policy↔data checks.")
    scan_p.add_argument("--target", help="Target family (bc|act|diffusion|openvla|pi0|octo).")
    scan_p.add_argument("--full", action="store_true", help="Exhaustive scan (default: fast triage).")
    scan_p.add_argument("--sample-episodes", type=int, default=None, help="Cap episodes scanned.")
    scan_p.add_argument("--no-vision", action="store_true", help="Skip image decoding.")
    scan_p.add_argument("--only", help="Run only matching detectors (comma-separated globs).")
    scan_p.add_argument("--disable", help="Skip matching detectors (comma-separated globs).")
    scan_p.add_argument("--seed", type=int, default=0, help="Deterministic sampling seed.")
    scan_p.add_argument(
        "--max-episode-memory",
        type=int,
        default=DEFAULT_MEMORY_BUDGET_MB,
        metavar="MB",
        help=(
            f"RAM budget for the trajectory working set (default {DEFAULT_MEMORY_BUDGET_MB} MiB). "
            "Exceeding it costs statistical power, never correctness: the retained episodes stay "
            "a uniform sample."
        ),
    )
    scan_p.add_argument("--fpr", type=float, default=DEFAULT_FPR, help="Target false-discovery rate.")
    scan_p.add_argument(
        "--calibration",
        help="Calibration corpus from `bohrin calibrate`; makes --fpr govern the covered gates.",
    )
    scan_p.add_argument("--lang", default="en", help="Report language code.")
    scan_p.add_argument(
        "--encoder",
        default="tiled",
        help="Visual encoder: tiled (offline default) or dinov2 (needs bohrin[vision]).",
    )
    scan_p.add_argument("--json", dest="json_path", help="Write the machine-readable Report JSON.")
    scan_p.add_argument("--html", dest="html_path", help="Write the self-contained HTML report.")
    scan_p.add_argument("--sarif", dest="sarif_path", help="Write a SARIF 2.1.0 log for GitHub code scanning.")
    scan_p.add_argument("--open", dest="open_html", action="store_true", help="Open the HTML report.")
    scan_p.add_argument("--ci", action="store_true", help="Quiet output; non-zero exit on gate.")
    scan_p.add_argument(
        "--fail-on",
        default="HIGH",
        choices=[s.value for s in Severity],
        help="CI gate severity.",
    )

    init_p = sub.add_parser("init", help="Infer the schema and write a bohrin.yaml.")
    init_p.add_argument("path", help="Dataset path.")
    init_p.add_argument("--format", help="Override format autodetection.")

    cal_p = sub.add_parser(
        "calibrate",
        help="Build a calibration corpus from KNOWN-GOOD datasets so --fpr governs the gates.",
    )
    cal_p.add_argument("paths", nargs="+", help="One or more datasets you have verified are clean.")
    cal_p.add_argument("-o", "--out", default="bohrin-calibration.json", help="Corpus file to write.")
    cal_p.add_argument("--format", help="Override format autodetection.")
    cal_p.add_argument("--seed", type=int, default=0, help="Deterministic sampling seed.")
    cal_p.add_argument("--full", action="store_true", help="Scan every episode (default: triage cap).")
    cal_p.add_argument(
        "--force",
        action="store_true",
        help="Collect even from a dataset that trips HIGH findings (teaches the gate its defects).",
    )

    sub.add_parser("list-detectors", help="List installed detectors (built-in + plugins).")

    explain_p = sub.add_parser("explain", help="Explain one detector's mechanism.")
    explain_p.add_argument("detector_id", help="A detector id, e.g. stats.dead_dimension.")

    sub.add_parser("version", help="Print the version.")
    return parser


def _cmd_scan(args: argparse.Namespace, console: Console, err: Console) -> int:
    if args.lang != "en" and not is_supported(args.lang):
        err.print(
            f"[yellow]note[/yellow] --lang {args.lang}: no catalog for that language yet "
            f"(have: {', '.join(supported_languages())}); rendering in English.",
            highlight=False,
        )
    try:
        with _progress(err, quiet=args.ci) as report_progress:
            report = scan(
                args.path,
                format=args.format,
                policy=args.policy,
                target=args.target,
                full=args.full,
                sample_episodes=args.sample_episodes,
                no_vision=args.no_vision,
                only=_split_csv(args.only),
                disable=_split_csv(args.disable),
                seed=args.seed,
                fpr=args.fpr,
                lang=args.lang,
                encoder=args.encoder,
                calibration=args.calibration,
                max_episode_memory_mb=args.max_episode_memory,
                progress=report_progress,
            )
    except _USER_ERRORS as exc:
        # These are all *user* errors — a wrong path, an unsupported container, an
        # unmappable schema, a bad checkpoint. Each already carries an actionable message,
        # so print it plainly. A traceback here would be noise on the most common first-run
        # mistake and would read as a crash in our tool rather than a fixable input.
        err.print(f"[red]error[/red] {exc}", highlight=False)
        return 2
    if args.json_path:
        report.to_json(args.json_path)
    if args.sarif_path:
        report.to_sarif(args.sarif_path)
    if args.html_path:
        report.to_html(args.html_path, lang=args.lang)
        if args.open_html:
            webbrowser.open(Path(args.html_path).resolve().as_uri())
    if not args.ci:
        TtyRenderer().print(report, console, lang=args.lang)
        _warn_if_vision_skipped(report, args, err)
    return _gate_exit_code(report, args.fail_on) if args.ci else 0


def _warn_if_vision_skipped(report: Report, args: argparse.Namespace, err: Console) -> None:
    """Tell the user when a dataset has cameras but no vision detector ran.

    Silence here would be dishonest: a report with no vision findings could mean 'cameras
    are fine' or 'cameras were never looked at'. We say which — usually a missing
    ``bohrin[video]`` for MP4-backed datasets, or a packed-video layout we don't decode yet.
    """
    if args.no_vision or not report.dataset.cameras:
        return
    if any(d.startswith("vision.") for d in report.detectors_run):
        return
    from bohrin.adapters._video import available as video_available

    hint = (
        "install bohrin[video] to analyze them"
        if not video_available()
        else "this dataset's video layout isn't decoded yet (packed per-file video)"
    )
    err.print(
        f"[yellow]note[/yellow] {len(report.dataset.cameras)} camera(s) detected but not "
        f"analyzed — {hint}. Pass --no-vision to silence.",
        highlight=False,
    )


def _cmd_init(args: argparse.Namespace, console: Console) -> int:
    from bohrin.adapters.registry import select_adapter

    adapter = select_adapter(args.path, forced_format=args.format)
    handle = adapter.open(Path(args.path), _init_config(args.path, args.format))
    schema = handle.schema()
    doc = {
        "format": adapter.name,
        "control_hz": schema.control_hz,
        "embodiment": schema.embodiment,
        "action_dim": schema.action_dim,
        "proprio_dim": schema.proprio_dim,
    }
    out = Path(args.path) / "bohrin.yaml" if Path(args.path).is_dir() else Path("bohrin.yaml")
    out.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    console.print(f"[green]wrote[/green] {out}  [dim](format: {adapter.name})[/dim]")
    return 0


def _init_config(path: str, fmt: str | None) -> ScanConfig:
    return ScanConfig(path=path, format=fmt)


def _cmd_calibrate(args: argparse.Namespace, console: Console, err: Console) -> int:
    """Build a calibration corpus from datasets the user has vouched for."""
    from bohrin.calibrate.collect import build_corpus
    from bohrin.calibrate.corpus import MIN_REFERENCE

    base = ScanConfig(path=args.paths[0], format=args.format, seed=args.seed, full=args.full)
    try:
        result = build_corpus(args.paths, base=base, force=args.force)
    except _USER_ERRORS as exc:
        err.print(f"[red]error[/red] {exc}", highlight=False)
        return 2

    for skipped in result.skipped:
        err.print(
            f"[yellow]skipped[/yellow] {skipped.path}: reports HIGH "
            f"({', '.join(skipped.high_findings)}). Calibrating on defective data teaches the "
            f"gate that the defect is normal. Fix it, or pass --force if the finding is a "
            f"known false positive.",
            highlight=False,
        )
    if not result.contributions:
        err.print("[red]error[/red] no dataset contributed reference scores; no corpus written.")
        return 2

    usable, undersized = result.usable_bands(), result.undersized_bands()
    result.corpus.save(args.out)
    total = sum(c.n_episodes for c in result.contributions)
    console.print(
        f"[green]wrote[/green] {args.out}  [dim]({len(result.contributions)} dataset(s), "
        f"{total} episodes, {len(usable)} usable band(s))[/dim]"
    )
    for key, n in usable.items():
        console.print(f"  [green]✓[/green] {key}  [dim]{n} reference scores[/dim]")
    for key, n in undersized.items():
        err.print(
            f"  [yellow]·[/yellow] {key}  [dim]{n} scores — under the {MIN_REFERENCE} needed; "
            f"still self-calibrating[/dim]"
        )
    if undersized:
        err.print(
            "[dim]note[/dim] calibrate on more known-good episodes to promote the remaining bands.",
            highlight=False,
        )
    # The band-size rule is not intuitive and silently decides whether a corpus does anything,
    # so state it here rather than letting a user discover an inert corpus by getting silence.
    console.print(
        "[dim]sizing:[/dim] a band needs roughly units÷fpr scores to decide a scan — a "
        "step-level check on 300 episodes at --fpr 0.01 wants ~30k reference scores. Findings "
        "say which gate ran, and name the shortfall when a band is too small.",
        highlight=False,
    )
    console.print(f"[dim]use it:[/dim] bohrin scan <dataset> --calibration {args.out}")
    return 0


def _gate_exit_code(report: Report, fail_on: str) -> int:
    gate = Severity(fail_on)
    worst = report.max_severity()
    return 1 if worst is not None and worst.rank >= gate.rank else 0


def _cmd_list_detectors(console: Console) -> int:
    for det in discover_detectors():
        console.print(f"[bold]{det.id}[/bold]  [dim]({det.family.value})[/dim]")
        if det.description:
            console.print(f"  {det.description}")
    return 0


def _cmd_explain(detector_id: str, console: Console, err: Console) -> int:
    for det in discover_detectors():
        if det.id == detector_id:
            console.print(f"[bold]{det.id}[/bold]  [dim]({det.family.value})[/dim]")
            console.print(det.explain())
            return 0
    err.print(f"[red]unknown detector:[/red] {detector_id}")
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the ``bohrin`` command. Returns a process exit code."""
    args = _build_parser().parse_args(argv)
    # Two consoles, deliberately (clig.dev): findings are the program's *output* and go to
    # stdout, while errors, notices and progress are *diagnostics* and go to stderr. That
    # is what lets `bohrin scan x --json - | jq` work without the human-readable chrome
    # landing in the pipe. Rich already honours NO_COLOR and non-TTY; --no-color forces it.
    console = Console(no_color=args.no_color or None)
    err = Console(stderr=True, no_color=args.no_color or None)
    if args.command == "scan":
        return _cmd_scan(args, console, err)
    if args.command == "init":
        return _cmd_init(args, console)
    if args.command == "calibrate":
        return _cmd_calibrate(args, console, err)
    if args.command == "list-detectors":
        return _cmd_list_detectors(console)
    if args.command == "explain":
        return _cmd_explain(args.detector_id, console, err)
    if args.command == "version":
        console.print(f"bohrin {__version__}")
        return 0
    return 2  # pragma: no cover - argparse enforces a valid subcommand


def _run() -> int:
    """Console-script wrapper: turn Ctrl-C into a clean exit rather than a traceback."""
    try:
        return main()
    except KeyboardInterrupt:  # pragma: no cover - requires a real SIGINT
        Console(stderr=True).print("[dim]interrupted[/dim]", highlight=False)
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_run())
