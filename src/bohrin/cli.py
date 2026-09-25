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
from bohrin.history import verify as history
from bohrin.history.git import GitError
from bohrin.report.sarif import to_sarif
from bohrin.stats.power import analyse, render
from bohrin.stats.results import read_results
from bohrin.version import __version__

CLEAN, FINDINGS, CANNOT_RUN, USAGE = 0, 1, 2, 64


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


def _parser() -> _Parser:
    parser = _Parser(
        prog="bohrin",
        description="Check the checker: find where a grader pays for work that was not done.",
        epilog="The specification: https://github.com/prabhu-gopal/bohrin/blob/main/docs/SPEC.md",
    )
    parser.add_argument("--version", action="version", version=f"bohrin {__version__}")
    verbs = parser.add_subparsers(dest="verb", metavar="COMMAND")
    power = verbs.add_parser(
        "power",
        help="check whether an evaluation is big enough to support what it is used to claim",
        description=(
            "Read a JSON Lines results file (task_id, model, score; optionally max_score, cluster, sample) and "
            "report each model's score with its interval, the smallest difference the evaluation can detect, "
            "paired comparisons between models, and an audit of how the scores were aggregated."
        ),
    )
    power.add_argument("file", type=Path, help="the results file, one JSON object per line")
    power.add_argument(
        "--min-difference",
        type=_fraction,
        metavar="FRACTION",
        help="the smallest difference you need to detect, such as 0.02; without it, size is reported but not judged",
    )
    power.add_argument("--json", action="store_true", help="print only the JSON report")
    check = verbs.add_parser(
        "verify",
        help="report what a change did to the tests and the code, beside what its commits claim",
        description=(
            "Compare the files at a commit with the working tree, uncommitted work included, and report facts read "
            "from syntax trees: tests deleted or weakened, checks removed, skips added, tolerances loosened, test "
            "hooks planted, functions replaced by stubs. Facts alone exit 0; facts beside a commit message that "
            "claims success exit 1. Needs no account and makes no network call."
        ),
    )
    check.add_argument(
        "--since",
        metavar="REF",
        help="the commit to compare from, such as HEAD~1 or main (default: where this branch started)",
    )
    check.add_argument("--strict", action="store_true", help="exit 1 on any fact, for CI")
    check.add_argument("--json", action="store_true", help="print only the JSON report")
    check.add_argument(
        "--sarif",
        type=Path,
        metavar="FILE",
        help="also write the facts as SARIF 2.1.0 to FILE, for code-scanning annotations on a pull request",
    )
    check.add_argument("path", nargs="?", type=Path, default=Path("."), help="a path inside the repository")

    more = verbs.add_parser("help", help="show the rarely used commands: bohrin help more")
    more.add_argument("topic", nargs="?", choices=["more"], help="more: the rarely used commands")

    conformance = verbs.add_parser(
        "conformance",
        help=argparse.SUPPRESS,
        description=(
            "Check a checking tool's results on the conformance suite's fixture graders, and print the level it "
            "achieves. The tool must flag every grader with a defect, with that defect's ID, and no correct grader. "
            "Runs no grader: it compares the results file with the suite's expected results."
        ),
    )
    # argparse lists a subcommand even with help=SUPPRESS; rare commands are listed by `help more` only.
    verbs._choices_actions = [a for a in verbs._choices_actions if a.dest != "conformance"]
    actions = conformance.add_subparsers(dest="action", metavar="ACTION", required=True)
    conformance_check = actions.add_parser("check", help="check a results file and print the level achieved")
    conformance_check.add_argument("file", type=Path, help="the tool's results, a conformance-results/v1 JSON file")
    conformance_check.add_argument("--json", action="store_true", help="print only the JSON report")
    return parser


#: The rarely used commands, shown by ``bohrin help more``.
MORE = """Rarely used commands:

  bohrin conformance check FILE   check a checking tool's results on the conformance suite, and print
                                  the level it achieves (BCL-1)
"""


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
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"bohrin: cannot open {path}: {exc.strerror}. Check the path and try again.", file=sys.stderr)
        return CANNOT_RUN
    except (UnicodeDecodeError, json.JSONDecodeError):
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
    parser = _parser()
    args = parser.parse_args(argv)
    if args.verb == "power":
        return _power(args)
    if args.verb == "verify":
        return _verify(args)
    if args.verb == "conformance":
        return _conformance(args)
    if args.verb == "help":
        if args.topic == "more":
            print(MORE, end="")
            return CLEAN
        parser.print_help()
        return CLEAN
    parser.print_help()
    return USAGE if argv else CLEAN


def run() -> NoReturn:
    """The console-script entry point."""
    sys.exit(main())


__all__ = ["CANNOT_RUN", "CLEAN", "FINDINGS", "USAGE", "main", "run"]
