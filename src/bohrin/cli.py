"""The ``bohrin`` command.

Every verb follows the same contract: a report on standard output (or, with ``--json``, only the
JSON document), errors and warnings on standard error, never a required prompt, and the same exit
codes everywhere:

====  ==========================================================
0     clean: nothing found in what was checked
1     findings
2     cannot run: the input could not be read
64    usage error
====  ==========================================================

Every command here needs no account and makes no network call.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

from bohrin import conformance
from bohrin._plugins import COMMANDS, load_plugin_classes
from bohrin.command import CANNOT_RUN, CLEAN, FINDINGS, USAGE, Command
from bohrin.evidence import _strict as strict
from bohrin.history import verify as history
from bohrin.history.git import GitError
from bohrin.report.sarif import to_sarif
from bohrin.stats.power import analyse, render
from bohrin.stats.results import read_results
from bohrin.version import __version__


class _Parser(argparse.ArgumentParser):
    """``argparse`` exits with 2 on a usage error; Bohrin's contract reserves 2 for 'cannot run'."""

    def error(self, message: str) -> NoReturn:
        """Print the usage and the problem, and exit with the usage-error code."""
        self.print_usage(sys.stderr)
        self.exit(USAGE, f"{self.prog}: {message}\n")


def _fraction(text: str) -> float:
    value = float(text)
    if not 0 < value < 1:
        raise argparse.ArgumentTypeError("give it as a fraction between 0 and 1, for example 0.02 for 2 points")
    return value


def _commands() -> list[Command]:
    """Every registered command: this package's in its fixed order, then others by name."""
    found = {name: cls for name, cls in load_plugin_classes(COMMANDS).items() if issubclass(cls, Command)}
    order = [*(n for n in _BUILTIN_ORDER if n in found), *sorted(set(found) - set(_BUILTIN_ORDER))]
    commands = []
    for name in order:
        command = found[name]()
        if not command.name:
            command.name = name
        commands.append(command)
    return commands


def _parser(commands: Sequence[Command]) -> _Parser:
    parser = _Parser(
        prog="bohrin",
        description="Check the checker: find where a grader pays for work that was not done.",
        epilog="The specification: https://github.com/prabhu-gopal/bohrin/blob/main/docs/SPEC.md",
    )
    parser.add_argument("--version", action="version", version=f"bohrin {__version__}")
    verbs = parser.add_subparsers(dest="verb", metavar="COMMAND")
    for command in commands:
        sub = verbs.add_parser(
            command.name,
            help=argparse.SUPPRESS if command.rare else command.help,
            description=command.description or command.help,
        )
        command.configure(sub)
        sub.set_defaults(command=command)
    more = verbs.add_parser("help", help="show the rarely used commands: bohrin help more")
    more.add_argument("topic", nargs="?", choices=["more"], help="more: the rarely used commands")
    # argparse lists a subcommand even with help=SUPPRESS; rare commands are listed by `help more` only.
    rare = {command.name for command in commands if command.rare}
    verbs._choices_actions = [a for a in verbs._choices_actions if a.dest not in rare]
    return parser


def _more(commands: Sequence[Command]) -> str:
    """The text of ``bohrin help more``: every rare command and what it does."""
    rare = [command for command in commands if command.rare]
    if not rare:
        return "There are no rarely used commands in this installation.\n"
    lines = ["Rarely used commands:", ""]
    lines += [f"  bohrin {command.usage or command.name:<28} {command.help}" for command in rare]
    return "\n".join(lines) + "\n"


class PowerCommand(Command):
    """``bohrin power``: is an evaluation big enough, and were its scores aggregated honestly?"""

    name = "power"
    help = "check whether an evaluation is big enough to support what it is used to claim"
    description = (
        "Read a JSON Lines results file (task_id, model, score; optionally max_score, cluster, sample) and "
        "report each model's score with its interval, the smallest difference the evaluation can detect, "
        "paired comparisons between models, and an audit of how the scores were aggregated."
    )

    def configure(self, parser: argparse.ArgumentParser) -> None:
        """The results file, the difference that matters, and JSON output."""
        parser.add_argument("file", type=Path, help="the results file, one JSON object per line")
        parser.add_argument(
            "--min-difference",
            type=_fraction,
            metavar="FRACTION",
            help="the smallest difference you need to detect, such as 0.02; without it, size is reported, not judged",
        )
        parser.add_argument("--json", action="store_true", help="print only the JSON report")

    def run(self, args: argparse.Namespace) -> int:
        """Analyse the file and print the report."""
        return _power(args)


class VerifyCommand(Command):
    """``bohrin verify``: what a change did to the tests and the code, beside what its commits claim."""

    name = "verify"
    help = "report what a change did to the tests and the code, beside what its commits claim"
    description = (
        "Compare the files at a commit with the working tree, uncommitted work included, and report facts read "
        "from syntax trees: tests deleted or weakened, checks removed, skips added, tolerances loosened, test "
        "hooks planted, functions replaced by stubs. Facts alone exit 0; facts beside a commit message that "
        "claims success exit 1. Needs no account and makes no network call."
    )

    def configure(self, parser: argparse.ArgumentParser) -> None:
        """Where to compare from, how strict to be, and the output formats."""
        parser.add_argument(
            "--since",
            metavar="REF",
            help="the commit to compare from, such as HEAD~1 or main (default: where this branch started)",
        )
        parser.add_argument("--strict", action="store_true", help="exit 1 on any fact, for CI")
        parser.add_argument("--json", action="store_true", help="print only the JSON report")
        parser.add_argument(
            "--sarif",
            type=Path,
            metavar="FILE",
            help="also write the facts as SARIF 2.1.0 to FILE, for code-scanning annotations on a pull request",
        )
        parser.add_argument("path", nargs="?", type=Path, default=Path("."), help="a path inside the repository")

    def run(self, args: argparse.Namespace) -> int:
        """Read the history and print the facts."""
        return _verify(args)


class ConformanceCommand(Command):
    """``bohrin conformance check``: the level a grader-checking tool's results achieve."""

    name = "conformance"
    help = "check a checking tool's results on the conformance suite, and print the level it achieves"
    description = (
        "Check a checking tool's results on the conformance suite's fixture graders, and print the level it "
        "achieves. The tool must flag every grader with a defect, with that defect's ID, and no correct grader. "
        "Runs no grader: it compares the results file with the suite's expected results."
    )
    rare = True
    usage = "conformance check FILE"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        """One action for now: check."""
        actions = parser.add_subparsers(dest="action", metavar="ACTION", required=True)
        check = actions.add_parser("check", help="check a results file and print the level achieved")
        check.add_argument("file", type=Path, help="the tool's results, a conformance-results/v1 JSON file")
        check.add_argument("--json", action="store_true", help="print only the JSON report")

    def run(self, args: argparse.Namespace) -> int:
        """Compare the results with the suite."""
        return _conformance(args)


#: This package's commands, in the order the command list shows them.
_BUILTIN_ORDER = ("power", "verify", "conformance")


def _power(args: argparse.Namespace) -> int:
    path: Path = args.file
    try:
        with path.open(encoding="utf-8") as handle:
            rows = read_results(handle)
    except OSError as exc:
        print(f"bohrin: cannot open {path}: {exc.strerror}. Check the path and try again.", file=sys.stderr)
        return CANNOT_RUN
    except UnicodeDecodeError:
        print(f"bohrin: {path} is not UTF-8 text. A results file is JSON Lines, one object per line.", file=sys.stderr)
        return CANNOT_RUN
    except ValueError as exc:
        print(
            f"bohrin: cannot read {path}: {exc}. Each line needs task_id, model and score; "
            "see 'bohrin power' in docs/SPEC.md.",
            file=sys.stderr,
        )
        return CANNOT_RUN
    report = analyse(rows, source=path.name, min_difference=args.min_difference)
    if args.json:
        print(json.dumps(report.to_json(), indent=2))
    else:
        print(render(report))
    return FINDINGS if report.findings else CLEAN


def _verify(args: argparse.Namespace) -> int:
    try:
        report = history.verify(args.path, args.since)
    except GitError as exc:
        print(
            f"bohrin: cannot read the history: {exc}. Run bohrin verify inside a git repository, "
            "with --since naming a commit that exists.",
            file=sys.stderr,
        )
        return CANNOT_RUN
    if args.sarif is not None:
        try:
            args.sarif.write_text(json.dumps(to_sarif(report), indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"bohrin: cannot write {args.sarif}: {exc.strerror}. Check the directory exists.", file=sys.stderr)
            return CANNOT_RUN
    if args.json:
        print(json.dumps(report.to_json(), indent=2))
    else:
        print(history.render(report))
    hard = any(fact.kind == "fact" for fact in report.facts)
    if hard and (args.strict or report.claims):
        return FINDINGS
    return CLEAN


def _conformance(args: argparse.Namespace) -> int:
    path: Path = args.file
    try:
        data = strict.load_json(path.read_text(encoding="utf-8"), str(path))
    except OSError as exc:
        print(f"bohrin: cannot open {path}: {exc.strerror}. Check the path and try again.", file=sys.stderr)
        return CANNOT_RUN
    except (UnicodeDecodeError, ValueError):
        print(f"bohrin: {path} is not a JSON document. See 'Conformance' in docs/SPEC.md.", file=sys.stderr)
        return CANNOT_RUN
    try:
        report = conformance.check(conformance.read_results(data))
    except ValueError as exc:
        print(f"bohrin: cannot check {path}: {exc}. See 'Conformance' in docs/SPEC.md.", file=sys.stderr)
        return CANNOT_RUN
    if args.json:
        print(json.dumps(report.to_json(), indent=2))
    else:
        print(conformance.render(report, source=path.name))
    return CLEAN if report.achieved else FINDINGS


def main(argv: Sequence[str] | None = None) -> int:
    """Run ``bohrin`` with ``argv`` (default: the process's arguments) and return its exit code."""
    commands = _commands()
    parser = _parser(commands)
    args = parser.parse_args(argv)
    command: Command | None = getattr(args, "command", None)
    if command is not None:
        return command.run(args)
    if args.verb == "help":
        if args.topic == "more":
            print(_more(commands), end="")
            return CLEAN
        parser.print_help()
        return CLEAN
    parser.print_help()
    return USAGE if argv else CLEAN


def run() -> NoReturn:
    """The console-script entry point."""
    sys.exit(main())


__all__ = [
    "CANNOT_RUN",
    "CLEAN",
    "FINDINGS",
    "USAGE",
    "ConformanceCommand",
    "PowerCommand",
    "VerifyCommand",
    "main",
    "run",
]
